"""HTTP routes for TokensGate.

The /v1/chat/completions handler is the spine of the gateway. Order of
operations is the structural commitment of the Execution Plan:

  1. Identify client (header > bearer > IP)
  2. Estimate input tokens for routing + rate-limit accounting
  3. Choose model (cost-aware router)
  4. Check + increment rate limit (returns 429 if exceeded)
  5. Try prompt cache (return immediately on hit)
  6. Call upstream via providers.call_with_failover()
       - Anthropic primary, with circuit-breaker gating
       - Ollama fallback when CB OPEN or retryable failure
  7. Cache the response
  8. Log metrics
  9. Return OpenAI-compatible response with TokensGate-* headers
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from app import circuit_breaker as cb
from app import providers as prov
from app.cache import (
    compute_cache_key,
    get_cached_response,
    set_cached_response,
)
from app import deps as deps_mod  # resolve singletons at call time (monkeypatch-safe)
from app.config import ENVIRONMENT
from app.deps import logger
from app.metrics import (
    get_aggregate_metrics,
    get_recent_requests,
    log_request_metrics,
)
from app.models import ChatCompletionRequest
from app.pricing import estimate_cost
from app.rate_limit import check_and_increment, client_id_from_request
from app.router import choose_model
from app.tokenizer import estimate_messages_tokens

router = APIRouter()


# ----------------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------------

@router.get("/health")
async def health_check() -> dict:
    # Resolve singletons at call time so test monkeypatches on app.deps.* take effect.
    redis_client = deps_mod.redis_client
    anthropic_client = deps_mod.anthropic_client

    if redis_client is None:
        redis_status = "not_configured"
    else:
        try:
            redis_client.ping()
            redis_status = "ok"
        except Exception as exc:  # noqa: BLE001
            redis_status = f"error: {exc}"

    return {
        "status": "healthy",
        "environment": ENVIRONMENT,
        "redis": redis_status,
        "anthropic": "ready" if anthropic_client else "not_configured",
        "circuit_breakers": cb.get_all_snapshots([prov.ANTHROPIC_TARGET, prov.OLLAMA_TARGET]),
        "timestamp": datetime.utcnow().isoformat(),
    }


# ----------------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------------

@router.get("/metrics")
async def get_metrics() -> dict:
    base = get_aggregate_metrics()
    base["circuit_breakers"] = cb.get_all_snapshots(
        [prov.ANTHROPIC_TARGET, prov.OLLAMA_TARGET]
    )
    return base


@router.get("/metrics/recent")
async def recent_metrics(limit: int = 20) -> dict:
    return {"requests": get_recent_requests(limit)}


# ----------------------------------------------------------------------------
# Dashboard
# ----------------------------------------------------------------------------

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    """Self-contained monitoring dashboard — no external dependencies."""
    redis_client = deps_mod.redis_client
    anthropic_client = deps_mod.anthropic_client

    # --- System status ---
    try:
        if redis_client is None:
            redis_status = "error"
        else:
            redis_client.ping()
            redis_status = "ok"
    except Exception:  # noqa: BLE001
        redis_status = "error"

    anthropic_status = "ok" if anthropic_client is not None else "error"
    gateway_status = "ok" if (redis_status == "ok" and anthropic_status == "ok") else "error"

    # --- Aggregate metrics (fail-safe) ---
    try:
        m = get_aggregate_metrics()
    except Exception:  # noqa: BLE001
        m = {
            "total_requests": 0,
            "total_errors": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": 0.0,
            "average_response_time_ms": 0.0,
            "cache": {"hits": 0, "misses": 0, "hit_rate": 0.0, "enabled": False},
        }

    cache_data = m.get("cache", {})
    hit_rate: float = float(cache_data.get("hit_rate", 0.0))
    total_req: int = int(m.get("total_requests", 0))
    total_err: int = int(m.get("total_errors", 0))
    error_rate: float = (total_err / total_req * 100) if total_req > 0 else 0.0
    total_in: int = int(m.get("total_input_tokens", 0))
    total_out: int = int(m.get("total_output_tokens", 0))
    avg_rt: float = float(m.get("average_response_time_ms", 0.0))
    total_cost: float = float(m.get("total_cost", 0.0))

    # --- Circuit breakers (fail-safe) ---
    try:
        cb_snap = cb.get_all_snapshots([prov.ANTHROPIC_TARGET, prov.OLLAMA_TARGET])
    except Exception:  # noqa: BLE001
        cb_snap = {
            "anthropic": {"state": "unknown", "failures_in_window": 0, "cooldown_remaining_s": 0, "opened_at_ms": None, "total_trips": 0},
            "ollama":    {"state": "unknown", "failures_in_window": 0, "cooldown_remaining_s": 0, "opened_at_ms": None, "total_trips": 0},
        }

    # --- Recent requests (fail-safe) ---
    try:
        recent = get_recent_requests(limit=20)
    except Exception:  # noqa: BLE001
        recent = []

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # -------------------------------------------------------------------------
    # Colour helpers (computed before the f-string — avoid complex expressions)
    # -------------------------------------------------------------------------
    def _status_color(s: str) -> str:
        return "#22c55e" if s == "ok" else "#ef4444"

    def _status_label(s: str) -> str:
        return "OK" if s == "ok" else "ERROR"

    def _cb_color(state: str) -> str:
        u = state.upper()
        if u == "CLOSED":
            return "#22c55e"
        if u == "OPEN":
            return "#ef4444"
        return "#f59e0b"

    def _cache_rate_color(rate: float) -> str:
        if rate >= 0.9:
            return "#22c55e"
        if rate >= 0.5:
            return "#f59e0b"
        return "#ef4444"

    def _status_cell_color(status: str) -> str:
        if status in ("success", "success_fallback"):
            return "#22c55e"
        if status == "error":
            return "#ef4444"
        if status == "rate_limited":
            return "#f59e0b"
        return "#9ca3af"

    def _fmt_time(ts: str) -> str:
        try:
            return ts[11:19]
        except Exception:  # noqa: BLE001
            return ts

    # -------------------------------------------------------------------------
    # Pre-built HTML fragments
    # -------------------------------------------------------------------------

    # System status cards
    redis_col  = _status_color(redis_status)
    redis_lbl  = _status_label(redis_status)
    anth_col   = _status_color(anthropic_status)
    anth_lbl   = _status_label(anthropic_status)
    gw_col     = _status_color(gateway_status)
    gw_lbl     = _status_label(gateway_status)

    # Circuit-breaker cards
    def _cb_card(name: str, snap: dict) -> str:
        state    = snap.get("state", "unknown")
        fails    = snap.get("failures_in_window", 0)
        cooldown = snap.get("cooldown_remaining_s", 0)
        trips    = snap.get("total_trips", 0)
        color    = _cb_color(state)
        cd_html  = (
            f'<p style="margin:4px 0;color:#f59e0b">Cooldown: {cooldown}s remaining</p>'
            if cooldown > 0 else ""
        )
        return (
            f'<div style="background:#1a1a1a;border-radius:8px;padding:16px;flex:1;min-width:200px">'
            f'<h3 style="margin:0 0 12px;color:#9ca3af;text-transform:uppercase;font-size:0.85rem">{name}</h3>'
            f'<p style="margin:4px 0"><span style="background:{color};color:#000;padding:2px 10px;'
            f'border-radius:4px;font-weight:bold;font-size:0.9rem">{state.upper()}</span></p>'
            f'<p style="margin:8px 0;font-family:monospace">Failures in window: {fails} / 5</p>'
            f'{cd_html}'
            f'<p style="margin:4px 0;color:#9ca3af;font-size:0.85rem">Lifetime trips: {trips}</p>'
            f'</div>'
        )

    ant_cb_html = _cb_card("Anthropic", cb_snap.get("anthropic", {}))
    ol_cb_html  = _cb_card("Ollama", cb_snap.get("ollama", {}))

    # Cache section
    cache_rate_col = _cache_rate_color(hit_rate)
    cache_pct      = f"{hit_rate * 100:.1f}%"
    cache_hits     = int(cache_data.get("hits", 0))
    cache_misses   = int(cache_data.get("misses", 0))
    cache_enabled  = bool(cache_data.get("enabled", False))
    cache_badge = (
        '<span style="background:#22c55e;color:#000;padding:2px 10px;border-radius:4px;'
        'font-size:0.85rem;font-weight:bold">ENABLED</span>'
        if cache_enabled else
        '<span style="background:#ef4444;color:#fff;padding:2px 10px;border-radius:4px;'
        'font-size:0.85rem;font-weight:bold">DISABLED</span>'
    )

    # Error rate colour
    err_col = "#ef4444" if error_rate > 5 else "#22c55e"

    # Environment badge colour
    env_col = "#3b82f6" if ENVIRONMENT == "production" else "#f59e0b"

    # Recent requests table rows
    if recent:
        rows_html = ""
        for req in recent:
            cost_obj  = req.get("cost", {})
            cache_hit = bool(req.get("cache_hit", False))
            status    = req.get("status", "")
            hit_col   = "#3b82f6" if cache_hit else "#9ca3af"
            hit_lbl   = "HIT" if cache_hit else "MISS"
            rt_ms     = req.get("response_time_ms", 0)
            rt_fmt    = f"{float(rt_ms):.1f}ms"
            rows_html += (
                f"<tr>"
                f'<td style="font-family:monospace">{_fmt_time(req.get("timestamp", ""))}</td>'
                f'<td>{req.get("client", "")}</td>'
                f'<td style="font-family:monospace;font-size:0.75rem">{req.get("model", "")}</td>'
                f'<td>{req.get("routing_strategy", "")}</td>'
                f'<td style="font-family:monospace;text-align:right">{req.get("input_tokens", 0)}</td>'
                f'<td style="font-family:monospace;text-align:right">{req.get("output_tokens", 0)}</td>'
                f'<td style="font-family:monospace;text-align:right">{rt_fmt}</td>'
                f'<td style="color:{hit_col};font-weight:bold">{hit_lbl}</td>'
                f'<td style="color:{_status_cell_color(status)};font-weight:bold">{status.upper()}</td>'
                f"</tr>"
            )
    else:
        rows_html = (
            '<tr><td colspan="9" style="text-align:center;color:#9ca3af;padding:24px">'
            "No requests recorded yet"
            "</td></tr>"
        )

    # -------------------------------------------------------------------------
    # HTML document
    # Note: CSS uses {{ }} to escape the f-string; all dynamic values above are
    # pre-computed as plain variables so the f-string body stays clean.
    # -------------------------------------------------------------------------
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta http-equiv="refresh" content="10">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>TokensGate Dashboard</title>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{background:#0f0f0f;color:#e5e7eb;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;padding:24px}}
  h1{{font-size:1.75rem;font-weight:700}}
  h2{{font-size:1.05rem;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:.05em;margin-bottom:12px}}
  section{{margin-bottom:32px}}
  .flex{{display:flex;gap:16px;flex-wrap:wrap}}
  .card{{background:#1a1a1a;border-radius:8px;padding:16px;flex:1;min-width:140px}}
  .stat-value{{font-family:monospace;font-size:1.4rem;font-weight:700;margin-top:6px}}
  .stat-label{{color:#9ca3af;font-size:0.8rem}}
  table{{width:100%;border-collapse:collapse;background:#1a1a1a;border-radius:8px;overflow:hidden}}
  th{{background:#111;color:#9ca3af;font-size:0.8rem;text-transform:uppercase;padding:10px 12px;text-align:left}}
  td{{padding:10px 12px;font-size:0.875rem;border-bottom:1px solid #222}}
  tr:last-child td{{border-bottom:none}}
</style>
</head>
<body>

<!-- Header -->
<section style="display:flex;align-items:center;gap:16px;margin-bottom:32px;flex-wrap:wrap">
  <div>
    <h1>TokensGate Dashboard</h1>
    <p style="color:#9ca3af;margin-top:4px;font-size:0.875rem">Last updated: {now_str} &nbsp;&middot;&nbsp; Auto-refreshes every 10s</p>
  </div>
  <span style="background:{env_col};color:#000;padding:4px 14px;border-radius:9999px;font-size:0.8rem;font-weight:700;text-transform:uppercase">{ENVIRONMENT}</span>
</section>

<!-- Section 1: System Status -->
<section>
  <h2>System Status</h2>
  <div class="flex">
    <div class="card">
      <div class="stat-label">Redis</div>
      <div class="stat-value" style="color:{redis_col}">{redis_lbl}</div>
    </div>
    <div class="card">
      <div class="stat-label">Anthropic</div>
      <div class="stat-value" style="color:{anth_col}">{anth_lbl}</div>
    </div>
    <div class="card">
      <div class="stat-label">Gateway</div>
      <div class="stat-value" style="color:{gw_col}">{gw_lbl}</div>
    </div>
  </div>
</section>

<!-- Section 2: Circuit Breakers -->
<section>
  <h2>Circuit Breakers</h2>
  <div class="flex">
    {ant_cb_html}
    {ol_cb_html}
  </div>
</section>

<!-- Section 3: Request Metrics -->
<section>
  <h2>Request Metrics</h2>
  <div class="flex">
    <div class="card">
      <div class="stat-label">Total Requests</div>
      <div class="stat-value">{total_req:,}</div>
    </div>
    <div class="card">
      <div class="stat-label">Error Rate</div>
      <div class="stat-value" style="color:{err_col}">{error_rate:.1f}%</div>
    </div>
    <div class="card">
      <div class="stat-label">Avg Response Time</div>
      <div class="stat-value">{avg_rt:.1f}<span style="font-size:0.9rem;color:#9ca3af">ms</span></div>
    </div>
    <div class="card">
      <div class="stat-label">Total Cost</div>
      <div class="stat-value">${total_cost:.6f}</div>
    </div>
  </div>
</section>

<!-- Section 4: Cache Performance -->
<section>
  <h2>Cache Performance</h2>
  <div class="flex">
    <div class="card" style="flex:2;min-width:200px">
      <div class="stat-label">Hit Rate</div>
      <div style="font-family:monospace;font-size:3rem;font-weight:700;color:{cache_rate_col};margin-top:6px">{cache_pct}</div>
      <div style="margin-top:10px">{cache_badge}</div>
    </div>
    <div class="card">
      <div class="stat-label">Cache Hits</div>
      <div class="stat-value" style="color:#22c55e">{cache_hits:,}</div>
    </div>
    <div class="card">
      <div class="stat-label">Cache Misses</div>
      <div class="stat-value" style="color:#ef4444">{cache_misses:,}</div>
    </div>
  </div>
</section>

<!-- Section 5: Token Usage -->
<section>
  <h2>Token Usage</h2>
  <div class="flex">
    <div class="card">
      <div class="stat-label">Input Tokens</div>
      <div class="stat-value">{total_in:,}</div>
    </div>
    <div class="card">
      <div class="stat-label">Output Tokens</div>
      <div class="stat-value">{total_out:,}</div>
    </div>
    <div class="card">
      <div class="stat-label">Total Tokens</div>
      <div class="stat-value">{total_in + total_out:,}</div>
    </div>
  </div>
</section>

<!-- Section 6: Recent Requests -->
<section>
  <h2>Recent Requests (last 20)</h2>
  <div style="overflow-x:auto">
    <table>
      <thead>
        <tr>
          <th>Time</th><th>Client</th><th>Model</th><th>Strategy</th>
          <th>Tokens In</th><th>Tokens Out</th><th>Latency</th><th>Cache</th><th>Status</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>
</section>

</body>
</html>"""

    return HTMLResponse(content=html)


# ----------------------------------------------------------------------------
# Main gateway endpoint
# ----------------------------------------------------------------------------

@router.post("/v1/chat/completions")
async def chat_completions(payload: ChatCompletionRequest, request: Request):
    start_time = time.time()
    request_id = uuid.uuid4().hex[:8]

    client = client_id_from_request(request)
    logger.info("req=%s client=%s incoming model=%s", request_id, client, payload.model)

    # If Anthropic isn't configured we can still potentially serve via Ollama
    # fallback, so we no longer 503 here unconditionally — let the provider
    # layer decide based on circuit state + config.

    # Step 2: estimate tokens (pre-call, tiktoken-based)
    estimated_input = estimate_messages_tokens(payload.messages)

    # Step 3: route
    routing = choose_model(request, payload.model, estimated_input)
    target_model = routing.model
    logger.info(
        "req=%s route strategy=%s model=%s reason=%s",
        request_id, routing.strategy, target_model, routing.reason,
    )

    # Step 4: rate limit
    rl = check_and_increment(client, estimated_input)
    if not rl.allowed:
        logger.warning(
            "req=%s RATE LIMITED client=%s reason=%s req=%d/%d tok=%d/%d",
            request_id, client, rl.reason,
            rl.request_count, rl.limit_requests,
            rl.token_count, rl.limit_tokens,
        )
        log_request_metrics(
            request_id=request_id,
            client=client,
            model=target_model,
            input_tokens=0,
            output_tokens=0,
            response_time_ms=(time.time() - start_time) * 1000,
            cache_hit=False,
            routing_strategy=routing.strategy,
            status="rate_limited",
            error=f"rate_limit:{rl.reason}",
        )
        return JSONResponse(
            status_code=429,
            content={
                "error": {
                    "type": "rate_limit_exceeded",
                    "reason": rl.reason,
                    "message": f"Exceeded {rl.reason} limit",
                    "limits": {
                        "requests_per_min": rl.limit_requests,
                        "tokens_per_min": rl.limit_tokens,
                    },
                    "current": {
                        "requests": rl.request_count,
                        "tokens": rl.token_count,
                    },
                }
            },
            headers={
                "Retry-After": str(rl.retry_after_seconds),
                "X-TokensGate-Client": client,
            },
        )

    # Step 5: cache lookup
    cache_key = compute_cache_key(
        model=target_model,
        temperature=payload.temperature or 0.7,
        max_tokens=payload.max_tokens or 1024,
        messages=payload.messages,
    )
    cached = get_cached_response(cache_key)

    if cached is not None:
        response_time_ms = (time.time() - start_time) * 1000
        cached_usage = cached.get("usage", {})
        log_request_metrics(
            request_id=request_id,
            client=client,
            model=target_model,
            input_tokens=int(cached_usage.get("prompt_tokens", 0)),
            output_tokens=0,  # no new output tokens billed on cache hit
            response_time_ms=response_time_ms,
            cache_hit=True,
            routing_strategy=routing.strategy,
            status="success",
        )
        cached = {**cached, "id": f"chatcmpl-{request_id}"}
        # Cache hits don't touch upstream — provider/fallback fields reflect
        # the original call that populated the cache (if recorded).
        cached_provider = cached.get("provider", "cache")
        return JSONResponse(
            content=cached,
            headers=_response_headers(
                request_id, "HIT", routing, rl, client,
                provider=cached_provider,
                fell_back=False,
                attempts=["cache:hit"],
            ),
        )

    # Step 6: call upstream via failover orchestrator
    try:
        result = prov.call_with_failover(
            messages=payload.messages,
            model=target_model,
            max_tokens=payload.max_tokens or 1024,
            temperature=payload.temperature or 0.7,
        )
    except prov.ProviderError as exc:
        response_time_ms = (time.time() - start_time) * 1000
        logger.error("req=%s upstream failover exhausted: %s", request_id, exc)
        # Failed call: do NOT bill estimated tokens — gateway owes nothing.
        log_request_metrics(
            request_id=request_id,
            client=client,
            model=target_model,
            input_tokens=0,
            output_tokens=0,
            response_time_ms=response_time_ms,
            cache_hit=False,
            routing_strategy=routing.strategy,
            status="error",
            error=str(exc),
        )
        # Surface CB context in the error response so clients can back off
        # intelligently. 503 reflects "we tried everything, nothing answered."
        cb_state = cb.get_all_snapshots(
            [prov.ANTHROPIC_TARGET, prov.OLLAMA_TARGET]
        )
        return JSONResponse(
            status_code=exc.status_code or 502,
            content={
                "error": {
                    "type": "upstream_unavailable",
                    "message": str(exc),
                    "circuit_breakers": cb_state,
                }
            },
            headers={
                "X-TokensGate-Request-Id": request_id,
                "X-TokensGate-Client": client,
                "X-TokensGate-Provider": exc.provider or "unknown",
            },
        )

    # Step 7: build OpenAI-compatible response
    input_tokens_actual = result.input_tokens
    output_tokens_actual = result.output_tokens
    response_time_ms = (time.time() - start_time) * 1000
    # Cost is computed against the model that actually responded. Ollama is
    # local → $0 cost regardless of model identifier.
    if result.provider == prov.OLLAMA_TARGET:
        cost = {
            "input_tokens": input_tokens_actual,
            "output_tokens": output_tokens_actual,
            "input_cost": 0.0,
            "output_cost": 0.0,
            "total_cost": 0.0,
            "model": result.model,
        }
    else:
        cost = estimate_cost(input_tokens_actual, output_tokens_actual, result.model)

    openai_response = {
        "id": f"chatcmpl-{request_id}",
        "object": "chat.completion",
        "created": int(start_time),
        "model": result.model,
        "provider": result.provider,
        "usage": {
            "prompt_tokens": input_tokens_actual,
            "completion_tokens": output_tokens_actual,
            "total_tokens": input_tokens_actual + output_tokens_actual,
        },
        "cost": cost,
        "routing": {
            "strategy": routing.strategy,
            "reason": routing.reason,
            "estimated_input_tokens": routing.estimated_input_tokens,
        },
        "gateway": {
            "attempts": result.attempts,
            "upstream_latency_ms": round(result.latency_ms, 2),
        },
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": result.text},
                "finish_reason": "stop",
            }
        ],
    }

    # Step 8: cache write (only cache successful primary-provider calls;
    # we don't want a single Ollama fallback poisoning the cache for hours).
    if result.provider == prov.ANTHROPIC_TARGET:
        set_cached_response(cache_key, openai_response)

    fell_back = result.provider != prov.ANTHROPIC_TARGET

    # Step 9: metrics + return
    log_request_metrics(
        request_id=request_id,
        client=client,
        model=result.model,
        input_tokens=input_tokens_actual,
        output_tokens=output_tokens_actual,
        response_time_ms=response_time_ms,
        cache_hit=False,
        routing_strategy=routing.strategy,
        status="success" if not fell_back else "success_fallback",
    )

    return JSONResponse(
        content=openai_response,
        headers=_response_headers(
            request_id, "MISS", routing, rl, client,
            provider=result.provider,
            fell_back=fell_back,
            attempts=result.attempts,
        ),
    )


def _response_headers(
    request_id,
    cache_state,
    routing,
    rl,
    client,
    *,
    provider: str = "unknown",
    fell_back: bool = False,
    attempts: list[str] | None = None,
) -> dict:
    """Standard TokensGate-* headers attached to every gateway response."""
    ant_state = cb.get_snapshot(prov.ANTHROPIC_TARGET).state.value
    ol_state = cb.get_snapshot(prov.OLLAMA_TARGET).state.value
    return {
        "X-Cache": cache_state,
        "X-TokensGate-Request-Id": request_id,
        "X-TokensGate-Client": client,
        "X-TokensGate-Model": routing.model,
        "X-TokensGate-Strategy": routing.strategy,
        "X-TokensGate-Provider": provider,
        "X-TokensGate-Fallback": "true" if fell_back else "false",
        "X-TokensGate-Attempts": ",".join(attempts or []),
        "X-TokensGate-CB-Anthropic": ant_state,
        "X-TokensGate-CB-Ollama": ol_state,
        "X-RateLimit-Remaining-Requests": str(max(0, rl.limit_requests - rl.request_count)),
        "X-RateLimit-Remaining-Tokens": str(max(0, rl.limit_tokens - rl.token_count)),
    }
