"""Provider abstraction over Anthropic and Ollama, with CB-aware failover.

Phase 3 of the execution plan. Two upstream providers, one uniform interface,
one orchestrator that routes between them based on circuit breaker state.

WHY ABSTRACT
============
Without this layer, api.py would carry SDK-specific branching for every
provider. Each new provider would multiply that branching. With a thin
``Provider`` interface, api.py just calls ``call_with_failover()`` and
gets back a normalized ``CompletionResult``.

ERROR CLASSIFICATION
====================
A failure that should trip the circuit is *retryable* — the provider itself
is unhealthy. A failure that shouldn't is *non-retryable* — the caller is
broken (4xx auth, bad request, validation). Only retryable failures hit
``record_failure()``.

  Retryable     5xx, 429, timeouts, connection errors
  Non-retryable 4xx (auth, validation, content moderation) — caller's bug

FAILOVER POLICY
===============
1. Check Anthropic's circuit. If allowed, try it.
2. On retryable failure: record failure, fall through to Ollama.
3. If Ollama's circuit is also OPEN: surface the original error (no point
   trying a downed fallback).
4. If Ollama succeeds: return the result tagged with provider="ollama" and
   the attempts list so api.py can populate the X-TokensGate-Fallback header.
5. If Ollama also fails: surface a combined ProviderError.

Non-retryable Anthropic errors short-circuit immediately — Ollama can't fix
a 401.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import List, Optional

import requests

from app import circuit_breaker as cb
from app.config import (
    OLLAMA_BASE_URL,
    OLLAMA_FALLBACK_ENABLED,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
)
from app import deps as deps_mod  # late-bound so tests can monkeypatch
from app.deps import logger
from app.models import Message


ANTHROPIC_TARGET = "anthropic"
OLLAMA_TARGET = "ollama"


# ---------------------------------------------------------------------------
# Result + error types
# ---------------------------------------------------------------------------

@dataclass
class CompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str            # actual model that responded
    provider: str         # "anthropic" | "ollama"
    latency_ms: float
    # Audit trail for observability: each attempt and its outcome.
    # e.g. ["anthropic:error:503", "ollama:ok"]
    attempts: List[str] = field(default_factory=list)


class ProviderError(Exception):
    """Provider call failed.

    ``is_retryable`` controls whether the circuit breaker treats this as a
    failure event. 5xx, 429, timeouts, connection errors → retryable.
    4xx auth/validation → not retryable (failover won't help).
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 0,
        is_retryable: bool = True,
        provider: str = "",
    ):
        super().__init__(message)
        self.status_code = status_code
        self.is_retryable = is_retryable
        self.provider = provider


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------

def _classify_anthropic_error(exc: Exception) -> ProviderError:
    """Turn an Anthropic SDK exception into a ProviderError with a sane flag."""
    # Lazy import so module load doesn't hard-require anthropic in odd envs.
    import anthropic as ant  # type: ignore

    if isinstance(exc, (ant.APITimeoutError, ant.APIConnectionError)):
        return ProviderError(
            f"Anthropic network/timeout: {exc}",
            status_code=0,
            is_retryable=True,
            provider=ANTHROPIC_TARGET,
        )
    if isinstance(exc, ant.APIStatusError):
        code = int(getattr(exc, "status_code", 0) or 0)
        retryable = code >= 500 or code == 429
        return ProviderError(
            f"Anthropic HTTP {code}: {exc}",
            status_code=code,
            is_retryable=retryable,
            provider=ANTHROPIC_TARGET,
        )
    # Unknown SDK error — treat as retryable so the circuit can react.
    return ProviderError(
        f"Anthropic error: {exc}",
        status_code=0,
        is_retryable=True,
        provider=ANTHROPIC_TARGET,
    )


class AnthropicProvider:
    name = ANTHROPIC_TARGET

    def generate(
        self,
        messages: List[Message],
        model: str,
        max_tokens: int,
        temperature: float,
    ) -> CompletionResult:
        # Resolve the client at CALL time, not import time — tests monkeypatch
        # app.deps.anthropic_client, and we want to honor that.
        client = deps_mod.anthropic_client
        if not client:
            raise ProviderError(
                "Anthropic client not configured",
                status_code=0,
                is_retryable=False,
                provider=ANTHROPIC_TARGET,
            )

        start = time.time()
        try:
            ant_messages = [{"role": m.role, "content": m.content} for m in messages]
            resp = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=ant_messages,
            )
        except Exception as exc:  # noqa: BLE001
            raise _classify_anthropic_error(exc) from exc

        text = resp.content[0].text if resp.content else ""
        return CompletionResult(
            text=text,
            input_tokens=int(getattr(resp.usage, "input_tokens", 0)),
            output_tokens=int(getattr(resp.usage, "output_tokens", 0)),
            model=model,
            provider=self.name,
            latency_ms=(time.time() - start) * 1000,
        )


# ---------------------------------------------------------------------------
# Ollama provider
# ---------------------------------------------------------------------------

class OllamaProvider:
    name = OLLAMA_TARGET

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = OLLAMA_MODEL,
        timeout_s: int = OLLAMA_TIMEOUT_SECONDS,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    def generate(
        self,
        messages: List[Message],
        model: Optional[str] = None,
        max_tokens: int = 1024,
        temperature: float = 0.7,
    ) -> CompletionResult:
        # Ollama ignores the upstream Claude model name; always use our local one.
        ollama_model = self.model
        ollama_messages = [{"role": m.role, "content": m.content} for m in messages]

        start = time.time()
        try:
            resp = requests.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": ollama_model,
                    "messages": ollama_messages,
                    "stream": False,
                    "options": {
                        "temperature": temperature,
                        "num_predict": max_tokens,
                    },
                },
                timeout=self.timeout_s,
            )
        except requests.Timeout as exc:
            raise ProviderError(
                f"Ollama timeout: {exc}",
                status_code=0,
                is_retryable=True,
                provider=OLLAMA_TARGET,
            ) from exc
        except requests.ConnectionError as exc:
            raise ProviderError(
                f"Ollama connection: {exc}",
                status_code=0,
                is_retryable=True,
                provider=OLLAMA_TARGET,
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"Ollama error: {exc}",
                status_code=0,
                is_retryable=True,
                provider=OLLAMA_TARGET,
            ) from exc

        if resp.status_code >= 500 or resp.status_code == 429:
            raise ProviderError(
                f"Ollama HTTP {resp.status_code}",
                status_code=resp.status_code,
                is_retryable=True,
                provider=OLLAMA_TARGET,
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"Ollama HTTP {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
                is_retryable=False,
                provider=OLLAMA_TARGET,
            )

        try:
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(
                f"Ollama invalid JSON: {exc}",
                status_code=0,
                is_retryable=True,
                provider=OLLAMA_TARGET,
            ) from exc

        # Ollama /api/chat shape:
        #   {"message": {"role": "assistant", "content": "..."},
        #    "prompt_eval_count": N, "eval_count": M, ...}
        message = data.get("message") or {}
        text = message.get("content", "") if isinstance(message, dict) else ""
        input_tokens = int(data.get("prompt_eval_count", 0) or 0)
        output_tokens = int(data.get("eval_count", 0) or 0)

        return CompletionResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model=ollama_model,
            provider=self.name,
            latency_ms=(time.time() - start) * 1000,
        )


# ---------------------------------------------------------------------------
# Module-level provider singletons (tests can monkeypatch)
# ---------------------------------------------------------------------------

anthropic_provider = AnthropicProvider()
ollama_provider = OllamaProvider()


# ---------------------------------------------------------------------------
# Failover orchestrator
# ---------------------------------------------------------------------------

def call_with_failover(
    messages: List[Message],
    model: str,
    max_tokens: int,
    temperature: float,
) -> CompletionResult:
    """Anthropic-first with CB-aware Ollama fallback.

    Flow:
      1. Check Anthropic circuit. If CLOSED/HALF_OPEN → try it.
      2. On retryable failure (or CB OPEN) → fall through to Ollama if allowed.
      3. On Ollama failure → raise the combined error.

    The returned ``CompletionResult.attempts`` list records every leg taken,
    which api.py exposes as ``X-TokensGate-Attempts`` for debugging.
    """
    attempts: List[str] = []

    # --- 1. Try Anthropic (if configured AND its circuit allows) ---
    # If the API key isn't set, skip Anthropic entirely — going through the
    # provider would raise a non-retryable error and block fallback, which
    # is wrong for the "Ollama-only" deployment shape. Treat absent-client
    # the same as an OPEN circuit.
    anthropic_configured = deps_mod.anthropic_client is not None
    ant_allowed, ant_snap = cb.allow_request(ANTHROPIC_TARGET)
    if anthropic_configured and ant_allowed:
        try:
            result = anthropic_provider.generate(
                messages=messages,
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            cb.record_success(ANTHROPIC_TARGET)
            attempts.append(f"{ANTHROPIC_TARGET}:ok")
            result.attempts = attempts
            return result
        except ProviderError as exc:
            if exc.is_retryable:
                cb.record_failure(ANTHROPIC_TARGET, status_code=exc.status_code)
                attempts.append(f"{ANTHROPIC_TARGET}:error:{exc.status_code or 'net'}")
                logger.warning(
                    "Primary (anthropic) failed retryably: %s — attempting failover",
                    exc,
                )
            else:
                # Non-retryable: don't trip the breaker, don't bother with Ollama.
                attempts.append(f"{ANTHROPIC_TARGET}:fatal:{exc.status_code}")
                exc.args = (f"{exc.args[0]} (attempts={attempts})",)
                raise
    elif not anthropic_configured:
        attempts.append(f"{ANTHROPIC_TARGET}:not_configured")
        logger.info("Anthropic client not configured — skipping straight to Ollama")
    else:
        attempts.append(f"{ANTHROPIC_TARGET}:cb_open")
        logger.info(
            "CB OPEN for anthropic (cooldown=%ds) — skipping straight to Ollama",
            ant_snap.cooldown_remaining_s,
        )

    # --- 2. Try Ollama fallback ---
    if not OLLAMA_FALLBACK_ENABLED:
        attempts.append(f"{OLLAMA_TARGET}:disabled")
        raise ProviderError(
            f"Anthropic unavailable and Ollama fallback disabled (attempts={attempts})",
            status_code=503,
            is_retryable=True,
            provider="gateway",
        )

    ol_allowed, ol_snap = cb.allow_request(OLLAMA_TARGET)
    if not ol_allowed:
        attempts.append(f"{OLLAMA_TARGET}:cb_open")
        raise ProviderError(
            f"Both providers unavailable: anthropic + ollama circuits OPEN "
            f"(ollama cooldown {ol_snap.cooldown_remaining_s}s, attempts={attempts})",
            status_code=503,
            is_retryable=True,
            provider="gateway",
        )

    try:
        result = ollama_provider.generate(
            messages=messages,
            model=None,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        cb.record_success(OLLAMA_TARGET)
        attempts.append(f"{OLLAMA_TARGET}:ok")
        result.attempts = attempts
        return result
    except ProviderError as exc:
        if exc.is_retryable:
            cb.record_failure(OLLAMA_TARGET, status_code=exc.status_code)
            attempts.append(f"{OLLAMA_TARGET}:error:{exc.status_code or 'net'}")
        else:
            attempts.append(f"{OLLAMA_TARGET}:fatal:{exc.status_code}")
        raise ProviderError(
            f"Failover exhausted: {exc} (attempts={attempts})",
            status_code=exc.status_code or 503,
            is_retryable=exc.is_retryable,
            provider="gateway",
        ) from exc
