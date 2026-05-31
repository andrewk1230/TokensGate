"""Tests for the provider abstraction + failover orchestrator.

Strategy:
  - For OllamaProvider, monkeypatch requests.post to simulate HTTP outcomes
    without any network.
  - For call_with_failover, monkeypatch the singleton providers' generate()
    methods to raise ProviderError directly. That isolates the failover
    decision tree from SDK-exception construction quirks.
  - For Anthropic SDK error classification, use simple subclasses that walk
    the same isinstance branches as the real SDK exceptions.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import requests

from app import circuit_breaker as cb
from app import providers as prov
from app.models import Message


# ---------------------------------------------------------------------------
# OllamaProvider — wire-level behavior with mocked requests.post
# ---------------------------------------------------------------------------

class _FakeOllamaResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or str(self._payload)

    def json(self):
        return self._payload


def test_ollama_provider_happy_path(monkeypatch):
    def fake_post(url, json=None, timeout=None):  # noqa: ARG001
        return _FakeOllamaResponse(
            200,
            {
                "message": {"role": "assistant", "content": "hello from llama"},
                "prompt_eval_count": 11,
                "eval_count": 7,
            },
        )

    monkeypatch.setattr(prov.requests, "post", fake_post)
    op = prov.OllamaProvider(base_url="http://fake", model="llama-x", timeout_s=5)

    result = op.generate([Message(role="user", content="hi")], max_tokens=64, temperature=0.5)
    assert result.text == "hello from llama"
    assert result.input_tokens == 11
    assert result.output_tokens == 7
    assert result.provider == prov.OLLAMA_TARGET
    assert result.model == "llama-x"


def test_ollama_provider_500_is_retryable(monkeypatch):
    monkeypatch.setattr(prov.requests, "post", lambda *a, **kw: _FakeOllamaResponse(503))
    op = prov.OllamaProvider(base_url="http://fake")
    with pytest.raises(prov.ProviderError) as ex:
        op.generate([Message(role="user", content="hi")])
    assert ex.value.is_retryable
    assert ex.value.status_code == 503


def test_ollama_provider_400_is_not_retryable(monkeypatch):
    monkeypatch.setattr(prov.requests, "post", lambda *a, **kw: _FakeOllamaResponse(400, text="bad"))
    op = prov.OllamaProvider(base_url="http://fake")
    with pytest.raises(prov.ProviderError) as ex:
        op.generate([Message(role="user", content="hi")])
    assert ex.value.is_retryable is False
    assert ex.value.status_code == 400


def test_ollama_provider_timeout_is_retryable(monkeypatch):
    def boom(*a, **kw):
        raise requests.Timeout("boom")
    monkeypatch.setattr(prov.requests, "post", boom)
    op = prov.OllamaProvider(base_url="http://fake")
    with pytest.raises(prov.ProviderError) as ex:
        op.generate([Message(role="user", content="hi")])
    assert ex.value.is_retryable


# ---------------------------------------------------------------------------
# AnthropicProvider — happy path with a stubbed client
# ---------------------------------------------------------------------------

class _FakeAnthropic:
    def __init__(self, text: str = "hi back", input_tokens: int = 5, output_tokens: int = 3):
        outer = self

        class _Messages:
            def create(self, **kwargs):  # noqa: ANN001, ARG002
                return SimpleNamespace(
                    content=[SimpleNamespace(text=text)],
                    usage=SimpleNamespace(
                        input_tokens=input_tokens,
                        output_tokens=output_tokens,
                    ),
                )

        self.messages = _Messages()


def test_anthropic_provider_happy_path(monkeypatch):
    from app import deps as deps_mod
    monkeypatch.setattr(deps_mod, "anthropic_client", _FakeAnthropic("ok", 12, 4))

    ap = prov.AnthropicProvider()
    result = ap.generate(
        [Message(role="user", content="ping")],
        model="claude-haiku-test",
        max_tokens=10,
        temperature=0.1,
    )
    assert result.text == "ok"
    assert result.input_tokens == 12
    assert result.output_tokens == 4
    assert result.provider == prov.ANTHROPIC_TARGET
    assert result.model == "claude-haiku-test"


def test_anthropic_provider_no_client_is_fatal(monkeypatch):
    from app import deps as deps_mod
    monkeypatch.setattr(deps_mod, "anthropic_client", None)

    ap = prov.AnthropicProvider()
    with pytest.raises(prov.ProviderError) as ex:
        ap.generate([Message(role="user", content="hi")], model="x", max_tokens=1, temperature=0)
    assert ex.value.is_retryable is False


def test_anthropic_unknown_exception_is_retryable(monkeypatch):
    """Unknown exception types fall through to the 'retryable' default."""
    class _Boom:
        class messages:
            @staticmethod
            def create(**kwargs):
                raise RuntimeError("kaboom")

    from app import deps as deps_mod
    monkeypatch.setattr(deps_mod, "anthropic_client", _Boom)

    ap = prov.AnthropicProvider()
    with pytest.raises(prov.ProviderError) as ex:
        ap.generate([Message(role="user", content="hi")], model="x", max_tokens=1, temperature=0)
    assert ex.value.is_retryable


# ---------------------------------------------------------------------------
# call_with_failover — the orchestrator decision tree
# ---------------------------------------------------------------------------

def _msgs():
    return [Message(role="user", content="hi")]


def _stub_provider(generate_fn):
    """Wrap a callable as a provider-like object exposing .generate()."""
    obj = SimpleNamespace()
    obj.generate = generate_fn
    return obj


def test_failover_returns_anthropic_when_healthy(monkeypatch):
    def ant_ok(**kwargs):  # noqa: ARG001
        return prov.CompletionResult(
            text="hello", input_tokens=1, output_tokens=1,
            model=kwargs["model"], provider=prov.ANTHROPIC_TARGET, latency_ms=1.0,
        )

    monkeypatch.setattr(prov, "anthropic_provider", _stub_provider(ant_ok))
    result = prov.call_with_failover(_msgs(), model="claude-x", max_tokens=10, temperature=0)
    assert result.provider == prov.ANTHROPIC_TARGET
    assert "anthropic:ok" in result.attempts


def test_failover_falls_back_on_retryable_anthropic_error(monkeypatch):
    def ant_500(**kwargs):  # noqa: ARG001
        raise prov.ProviderError(
            "anthropic 503", status_code=503, is_retryable=True,
            provider=prov.ANTHROPIC_TARGET,
        )

    def ol_ok(**kwargs):  # noqa: ARG001
        return prov.CompletionResult(
            text="fallback hi", input_tokens=2, output_tokens=2,
            model="llama-x", provider=prov.OLLAMA_TARGET, latency_ms=1.0,
        )

    monkeypatch.setattr(prov, "anthropic_provider", _stub_provider(ant_500))
    monkeypatch.setattr(prov, "ollama_provider", _stub_provider(ol_ok))

    result = prov.call_with_failover(_msgs(), model="claude-x", max_tokens=10, temperature=0)
    assert result.provider == prov.OLLAMA_TARGET
    assert result.text == "fallback hi"
    assert any("anthropic:error" in a for a in result.attempts)
    assert "ollama:ok" in result.attempts


def test_failover_does_not_fallback_on_non_retryable_anthropic_error(monkeypatch):
    """4xx auth errors should surface directly — Ollama can't fix a bad API key."""
    def ant_401(**kwargs):  # noqa: ARG001
        raise prov.ProviderError(
            "anthropic 401", status_code=401, is_retryable=False,
            provider=prov.ANTHROPIC_TARGET,
        )

    def ol_should_not_run(**kwargs):  # noqa: ARG001
        raise AssertionError("ollama must not be called on non-retryable anthropic error")

    monkeypatch.setattr(prov, "anthropic_provider", _stub_provider(ant_401))
    monkeypatch.setattr(prov, "ollama_provider", _stub_provider(ol_should_not_run))

    with pytest.raises(prov.ProviderError) as ex:
        prov.call_with_failover(_msgs(), model="claude-x", max_tokens=10, temperature=0)
    assert ex.value.status_code == 401
    assert ex.value.is_retryable is False


def test_failover_raises_when_both_unavailable(monkeypatch):
    def ant_500(**kwargs):  # noqa: ARG001
        raise prov.ProviderError("ant down", status_code=502, is_retryable=True, provider=prov.ANTHROPIC_TARGET)

    def ol_500(**kwargs):  # noqa: ARG001
        raise prov.ProviderError("ol down", status_code=502, is_retryable=True, provider=prov.OLLAMA_TARGET)

    monkeypatch.setattr(prov, "anthropic_provider", _stub_provider(ant_500))
    monkeypatch.setattr(prov, "ollama_provider", _stub_provider(ol_500))

    with pytest.raises(prov.ProviderError) as ex:
        prov.call_with_failover(_msgs(), model="claude-x", max_tokens=10, temperature=0)
    # Both attempts should be recorded in the error message
    assert "anthropic:error" in str(ex.value)
    assert "ollama:error" in str(ex.value)


def test_failover_skips_anthropic_when_circuit_open(monkeypatch):
    """If Anthropic's CB is OPEN, we should go straight to Ollama (no Anthropic call)."""
    # Trip the Anthropic breaker by recording threshold failures
    from app.config import CB_FAILURE_THRESHOLD
    for _ in range(CB_FAILURE_THRESHOLD):
        cb.record_failure(prov.ANTHROPIC_TARGET, status_code=503)

    def ant_should_not_run(**kwargs):  # noqa: ARG001
        raise AssertionError("anthropic must not be called when its circuit is OPEN")

    def ol_ok(**kwargs):  # noqa: ARG001
        return prov.CompletionResult(
            text="from ollama", input_tokens=1, output_tokens=1,
            model="llama-x", provider=prov.OLLAMA_TARGET, latency_ms=1.0,
        )

    monkeypatch.setattr(prov, "anthropic_provider", _stub_provider(ant_should_not_run))
    monkeypatch.setattr(prov, "ollama_provider", _stub_provider(ol_ok))

    result = prov.call_with_failover(_msgs(), model="claude-x", max_tokens=10, temperature=0)
    assert result.provider == prov.OLLAMA_TARGET
    assert "anthropic:cb_open" in result.attempts


def test_failover_skips_anthropic_when_client_not_configured(monkeypatch):
    """Edge case: if CLAUDE_API_KEY isn't set, anthropic_client is None.
    Gateway must skip straight to Ollama (treat absent-client as CB-open)
    rather than 401-ing the client."""
    from app import deps as deps_mod
    monkeypatch.setattr(deps_mod, "anthropic_client", None)

    def ant_should_not_run(**kwargs):  # noqa: ARG001
        raise AssertionError("anthropic must not be called when client is None")

    def ol_ok(**kwargs):  # noqa: ARG001
        return prov.CompletionResult(
            text="ollama only", input_tokens=1, output_tokens=1,
            model="llama-x", provider=prov.OLLAMA_TARGET, latency_ms=1.0,
        )

    monkeypatch.setattr(prov, "anthropic_provider", _stub_provider(ant_should_not_run))
    monkeypatch.setattr(prov, "ollama_provider", _stub_provider(ol_ok))

    result = prov.call_with_failover(_msgs(), model="claude-x", max_tokens=10, temperature=0)
    assert result.provider == prov.OLLAMA_TARGET
    assert "anthropic:not_configured" in result.attempts


def test_failover_disabled_ollama_raises(monkeypatch):
    """If OLLAMA_FALLBACK_ENABLED is False, a failed anthropic should not try ollama."""
    monkeypatch.setattr(prov, "OLLAMA_FALLBACK_ENABLED", False)

    def ant_500(**kwargs):  # noqa: ARG001
        raise prov.ProviderError("ant down", status_code=503, is_retryable=True, provider=prov.ANTHROPIC_TARGET)

    def ol_should_not_run(**kwargs):  # noqa: ARG001
        raise AssertionError("ollama must not be called when fallback is disabled")

    monkeypatch.setattr(prov, "anthropic_provider", _stub_provider(ant_500))
    monkeypatch.setattr(prov, "ollama_provider", _stub_provider(ol_should_not_run))

    with pytest.raises(prov.ProviderError) as ex:
        prov.call_with_failover(_msgs(), model="claude-x", max_tokens=10, temperature=0)
    assert "fallback disabled" in str(ex.value) or "ollama:disabled" in str(ex.value)
