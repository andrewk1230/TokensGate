"""Phase 3 failover benchmark for TokensGate.

Measures the four resume-grade numbers for fault tolerance:

  1. **Outage detection time** — how long from the first Anthropic failure
     until the breaker trips OPEN (≈ threshold × per-call latency).
  2. **Failover overhead** — added latency on the first few requests that
     hit a failing Anthropic before the breaker is OPEN.
  3. **Steady-state failover latency** — once OPEN, requests skip Anthropic
     entirely and run only through Ollama. This is the user-visible
     "during the outage" latency.
  4. **Recovery time** — from the moment Anthropic comes back to the
     moment the breaker closes (= cooldown + canary RTT).

The deliverable bullet:
    "Zero requests dropped during a simulated 30-second Anthropic outage;
     gateway detected the failure in <X>ms, served the remaining N requests
     via local Ollama fallback at <Y>ms p50, and auto-recovered in <Z>s
     when the primary came back online."

Two modes:
  --mode=mock   (default)  fakeredis + stubbed providers; deterministic, free,
                           fully exercises the CB state machine in <2 seconds.
  --mode=live              hits a running docker-compose stack. Requires you
                           to simulate an Anthropic outage out-of-band (e.g.
                           by setting CLAUDE_API_KEY to a bogus value and
                           restarting the gateway container).

Usage:
  python benchmark_failover.py --mode=mock
  python benchmark_failover.py --mode=mock --phase-requests=20 --cooldown=3
  python benchmark_failover.py --mode=live --base-url=http://localhost:8000 \
      --total-requests=60
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from types import SimpleNamespace
from typing import List, Tuple


# ---------------------------------------------------------------------------
# Mock mode
# ---------------------------------------------------------------------------

class _ToggleStub:
    """Anthropic + Ollama stubs that can be flipped healthy↔broken mid-run.

    Each stub records the wall-clock time of every call so we can compute
    detection latency precisely.
    """

    def __init__(self, name: str, healthy_latency_ms: float, broken_latency_ms: float):
        self.name = name
        self.healthy_latency_ms = healthy_latency_ms
        self.broken_latency_ms = broken_latency_ms
        self.healthy = True
        self.call_log: List[Tuple[float, bool]] = []  # (timestamp, was_healthy)


def _build_anthropic_stub(stub: _ToggleStub):
    """Return an object shaped like the Anthropic SDK client."""
    class _Messages:
        def create(self, **kwargs):  # noqa: ANN001, ARG002
            stub.call_log.append((time.time(), stub.healthy))
            time.sleep(stub.healthy_latency_ms / 1000.0)
            if not stub.healthy:
                # Construct an ant exception that classifies as retryable 5xx
                from app.providers import ProviderError, ANTHROPIC_TARGET
                raise ProviderError(
                    "simulated 503",
                    status_code=503,
                    is_retryable=True,
                    provider=ANTHROPIC_TARGET,
                )
            input_tokens = sum(len(m["content"].split()) for m in kwargs["messages"]) * 2
            return SimpleNamespace(
                content=[SimpleNamespace(text="[anthropic ok]")],
                usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=50),
            )

    return SimpleNamespace(messages=_Messages())


def _patch_ollama_stub(stub: _ToggleStub):
    """Return an OllamaProvider.generate replacement."""
    from app.providers import CompletionResult, OLLAMA_TARGET

    def generate(messages, model=None, max_tokens=1024, temperature=0.7):  # noqa: ARG001
        stub.call_log.append((time.time(), stub.healthy))
        time.sleep(stub.healthy_latency_ms / 1000.0)
        if not stub.healthy:
            from app.providers import ProviderError
            raise ProviderError("ollama down", status_code=502, is_retryable=True, provider=OLLAMA_TARGET)
        input_tokens = sum(len(m.content.split()) for m in messages) * 2
        return CompletionResult(
            text="[ollama fallback ok]",
            input_tokens=input_tokens,
            output_tokens=20,
            model="llama-stub",
            provider=OLLAMA_TARGET,
            latency_ms=stub.healthy_latency_ms,
        )

    return generate


def _make_anthropic_provider_generate(ant_stub: _ToggleStub):
    """Wrap the stub so it goes through providers.AnthropicProvider semantics."""
    def generate(messages, model, max_tokens, temperature):
        # Reuse the providers.AnthropicProvider code path by calling its
        # underlying client manually — simpler than re-implementing all of it.
        from app import deps as deps_mod
        from app.providers import AnthropicProvider
        ap = AnthropicProvider()
        # Temporarily ensure the deps client is our stub
        deps_mod.anthropic_client = _build_anthropic_stub(ant_stub)
        return ap.generate(messages, model, max_tokens, temperature)
    return generate


def run_mock(args) -> dict:
    """Run all three phases against a stubbed gateway in-process."""
    # Set env BEFORE importing app modules so a short cooldown is picked up.
    os.environ["CLAUDE_API_KEY"] = "mock-key"
    os.environ["RATE_LIMIT_REQUESTS_PER_MIN"] = "10000"
    os.environ["RATE_LIMIT_TOKENS_PER_MIN"] = "100000000"
    os.environ["CB_FAILURE_THRESHOLD"] = str(args.threshold)
    os.environ["CB_WINDOW_SECONDS"] = str(args.window)
    os.environ["CB_COOLDOWN_SECONDS"] = str(args.cooldown)

    import fakeredis
    from fastapi.testclient import TestClient

    from app import api as api_mod
    from app import cache as cache_mod
    from app import circuit_breaker as cb_mod
    from app import deps as deps_mod
    from app import metrics as metrics_mod
    from app import providers as prov_mod
    from app import rate_limit as rl_mod

    # Wire fakeredis everywhere
    fake = fakeredis.FakeRedis(decode_responses=True)
    for mod in (deps_mod, cache_mod, rl_mod, metrics_mod, cb_mod):
        mod.redis_client = fake

    # Stubs for the two upstreams
    ant_stub = _ToggleStub("anthropic", args.anthropic_latency_ms, args.anthropic_latency_ms)
    ol_stub = _ToggleStub("ollama", args.ollama_latency_ms, args.ollama_latency_ms)

    # Replace the underlying anthropic client with our toggleable stub.
    # We DON'T monkeypatch anthropic_provider.generate directly because then
    # the breaker doesn't see the right shape — we want the real provider
    # error-classification path to run.
    deps_mod.anthropic_client = _build_anthropic_stub(ant_stub)
    api_mod.anthropic_client = deps_mod.anthropic_client
    # Note: the stub's `healthy` flag is captured by closure inside _build_anthropic_stub,
    # so re-binding deps.anthropic_client later (we don't) would orphan the stub.
    # We toggle ant_stub.healthy directly; the stub's create() reads it on every call.

    # Ollama: cheaper to swap the whole generate method
    prov_mod.ollama_provider.generate = _patch_ollama_stub(ol_stub)

    from main import app
    client = TestClient(app)

    # ----- Phase A: Healthy baseline -----
    print(f"\n[Phase A] {args.phase_requests} requests with Anthropic HEALTHY", file=sys.stderr)
    phase_a = _drive(client, args.phase_requests, prefix="A")

    # ----- Phase B: Simulated Anthropic outage -----
    print(f"\n[Phase B] flipping Anthropic to BROKEN", file=sys.stderr)
    ant_stub.healthy = False
    outage_start = time.time()
    phase_b = _drive(client, args.phase_requests, prefix="B")
    # Detection: when did the breaker first flip OPEN?
    cb_snap = cb_mod.get_snapshot(prov_mod.ANTHROPIC_TARGET)
    detection_ms = None
    if cb_snap.opened_at_ms:
        detection_ms = cb_snap.opened_at_ms / 1000.0 - outage_start
        detection_ms *= 1000  # to ms

    # ----- Phase C: Recovery -----
    print(f"\n[Phase C] flipping Anthropic back to HEALTHY; waiting cooldown ({args.cooldown}s)", file=sys.stderr)
    ant_stub.healthy = True
    recovery_start = time.time()
    # Sleep slightly past the cooldown so the next request becomes the canary.
    time.sleep(args.cooldown + 0.5)
    phase_c = _drive(client, args.phase_requests, prefix="C")
    recovery_ms = (time.time() - recovery_start) * 1000

    metrics_snapshot = client.get("/metrics").json()

    return _summarize(
        phase_a, phase_b, phase_c,
        detection_ms=detection_ms,
        recovery_ms=recovery_ms,
        metrics=metrics_snapshot,
        cooldown_s=args.cooldown,
        threshold=args.threshold,
        mode="mock",
    )


def _drive(client, n: int, prefix: str) -> dict:
    """Send n requests, capture per-request stats."""
    rows = []
    for i in range(n):
        t0 = time.time()
        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": f"{prefix}-{i}-{time.time_ns()}"}]},
            headers={"X-Client-ID": f"bench-{prefix}"},
        )
        elapsed_ms = (time.time() - t0) * 1000
        rows.append({
            "i": i,
            "status": r.status_code,
            "provider": r.headers.get("X-TokensGate-Provider", "?"),
            "fallback": r.headers.get("X-TokensGate-Fallback") == "true",
            "cb_ant": r.headers.get("X-TokensGate-CB-Anthropic", "?"),
            "attempts": r.headers.get("X-TokensGate-Attempts", ""),
            "latency_ms": round(elapsed_ms, 2),
        })
    return {"rows": rows}


def _summarize(phase_a, phase_b, phase_c, *, detection_ms, recovery_ms, metrics, cooldown_s, threshold, mode) -> dict:
    def lat_stats(rows):
        ok = [r["latency_ms"] for r in rows if r["status"] == 200]
        if not ok:
            return {"p50": 0.0, "p95": 0.0, "ok_count": 0, "total": len(rows)}
        p50 = round(statistics.median(ok), 2)
        p95 = round(sorted(ok)[int(len(ok) * 0.95) - 1] if len(ok) >= 20 else max(ok), 2)
        return {"p50": p50, "p95": p95, "ok_count": len(ok), "total": len(rows)}

    a_stats = lat_stats(phase_a["rows"])
    b_stats = lat_stats(phase_b["rows"])
    c_stats = lat_stats(phase_c["rows"])

    # Provider mix in each phase
    def provider_mix(rows):
        mix: dict = {}
        for r in rows:
            mix[r["provider"]] = mix.get(r["provider"], 0) + 1
        return mix

    # Phase B subdivision: pre-trip (fallback=true) vs post-trip (cb_open seen)
    b_pre_trip = [r for r in phase_b["rows"] if r["fallback"] and "anthropic:error" in r["attempts"]]
    b_post_trip = [r for r in phase_b["rows"] if "anthropic:cb_open" in r["attempts"]]
    b_pre_lat = lat_stats(b_pre_trip)
    b_post_lat = lat_stats(b_post_trip)

    requests_total = a_stats["total"] + b_stats["total"] + c_stats["total"]
    requests_ok = a_stats["ok_count"] + b_stats["ok_count"] + c_stats["ok_count"]

    return {
        "mode": mode,
        "config": {
            "threshold": threshold,
            "cooldown_s": cooldown_s,
        },
        "totals": {
            "requests_total": requests_total,
            "requests_ok": requests_ok,
            "requests_dropped": requests_total - requests_ok,
            "uptime_pct": round(100 * requests_ok / requests_total, 2) if requests_total else 0.0,
        },
        "phase_A_healthy": {
            "latency_ms_p50": a_stats["p50"],
            "latency_ms_p95": a_stats["p95"],
            "provider_mix": provider_mix(phase_a["rows"]),
        },
        "phase_B_outage": {
            "latency_ms_p50": b_stats["p50"],
            "latency_ms_p95": b_stats["p95"],
            "provider_mix": provider_mix(phase_b["rows"]),
            "pre_trip": {
                "count": len(b_pre_trip),
                "latency_ms_p50": b_pre_lat["p50"],
            },
            "post_trip_steady_state": {
                "count": len(b_post_trip),
                "latency_ms_p50": b_post_lat["p50"],
            },
            "detection_latency_ms": round(detection_ms, 2) if detection_ms is not None else None,
        },
        "phase_C_recovery": {
            "latency_ms_p50": c_stats["p50"],
            "latency_ms_p95": c_stats["p95"],
            "provider_mix": provider_mix(phase_c["rows"]),
            "wall_clock_recovery_ms": round(recovery_ms, 2),
        },
        "circuit_breaker_final": metrics.get("circuit_breakers", {}),
    }


# ---------------------------------------------------------------------------
# Live mode (against a running stack)
# ---------------------------------------------------------------------------

def run_live(args) -> dict:
    """Hit a running gateway. To exercise failover, you must induce an outage
    out-of-band (e.g. set CLAUDE_API_KEY=bogus then restart the gateway
    container). This mode just measures what's happening end-to-end and
    reports the provider mix + uptime numbers."""
    try:
        import httpx
    except ImportError:
        sys.exit("ERROR: httpx not installed; pip install httpx")

    rows = []
    with httpx.Client(base_url=args.base_url, timeout=120.0) as client:
        try:
            client.get("/health").raise_for_status()
        except Exception as exc:  # noqa: BLE001
            sys.exit(f"ERROR: gateway not reachable at {args.base_url} ({exc})")

        for i in range(args.total_requests):
            t0 = time.time()
            try:
                r = client.post(
                    "/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": f"failover-bench-{i}-{time.time_ns()}"}]},
                    headers={"X-Client-ID": "bench-live"},
                )
                rows.append({
                    "i": i,
                    "status": r.status_code,
                    "provider": r.headers.get("X-TokensGate-Provider", "?"),
                    "fallback": r.headers.get("X-TokensGate-Fallback") == "true",
                    "cb_ant": r.headers.get("X-TokensGate-CB-Anthropic", "?"),
                    "attempts": r.headers.get("X-TokensGate-Attempts", ""),
                    "latency_ms": round((time.time() - t0) * 1000, 2),
                })
            except httpx.HTTPError as exc:
                rows.append({"i": i, "status": "network_error", "error": str(exc),
                             "latency_ms": round((time.time() - t0) * 1000, 2)})

        metrics = client.get("/metrics").json()

    ok_rows = [r for r in rows if r.get("status") == 200]
    via_anthropic = sum(1 for r in ok_rows if r["provider"] == "anthropic")
    via_ollama = sum(1 for r in ok_rows if r["provider"] == "ollama")
    latencies = [r["latency_ms"] for r in ok_rows]
    p50 = round(statistics.median(latencies), 2) if latencies else 0.0
    p95 = round(sorted(latencies)[int(len(latencies) * 0.95) - 1], 2) if len(latencies) >= 20 else 0.0

    return {
        "mode": "live",
        "totals": {
            "requests_total": len(rows),
            "requests_ok": len(ok_rows),
            "uptime_pct": round(100 * len(ok_rows) / len(rows), 2) if rows else 0.0,
        },
        "provider_mix": {"anthropic": via_anthropic, "ollama": via_ollama},
        "latency_ms_p50": p50,
        "latency_ms_p95": p95,
        "circuit_breakers": metrics.get("circuit_breakers", {}),
        "sample_rows": rows[:5] + (["..."] if len(rows) > 10 else []) + rows[-5:],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["mock", "live"], default="mock")
    # Mock-mode knobs
    p.add_argument("--phase-requests", type=int, default=15,
                   help="Requests in each of the 3 phases (healthy, outage, recovery)")
    p.add_argument("--anthropic-latency-ms", type=float, default=20,
                   help="Simulated Anthropic per-call latency in ms")
    p.add_argument("--ollama-latency-ms", type=float, default=40,
                   help="Simulated Ollama per-call latency in ms")
    p.add_argument("--threshold", type=int, default=5,
                   help="CB_FAILURE_THRESHOLD for the mock run")
    p.add_argument("--window", type=int, default=30,
                   help="CB_WINDOW_SECONDS for the mock run")
    p.add_argument("--cooldown", type=int, default=2,
                   help="CB_COOLDOWN_SECONDS for the mock run (kept short for benchmark speed)")
    # Live-mode knobs
    p.add_argument("--total-requests", type=int, default=60)
    p.add_argument("--base-url", default="http://localhost:8000")
    args = p.parse_args()

    if args.mode == "mock":
        result = run_mock(args)
    else:
        result = run_live(args)

    print(json.dumps(result, indent=2))

    # Resume-line preview
    print("\n--- Resume-line preview ---", file=sys.stderr)
    if args.mode == "mock":
        det = result["phase_B_outage"]["detection_latency_ms"]
        post = result["phase_B_outage"]["post_trip_steady_state"]["latency_ms_p50"]
        rec = result["phase_C_recovery"]["wall_clock_recovery_ms"]
        uptime = result["totals"]["uptime_pct"]
        dropped = result["totals"]["requests_dropped"]
        print(
            f"Uptime: {uptime}% ({dropped} dropped) | "
            f"Detection: {det}ms | "
            f"Steady-state failover p50: {post}ms | "
            f"Recovery: {rec/1000:.1f}s",
            file=sys.stderr,
        )
    else:
        print(
            f"Uptime: {result['totals']['uptime_pct']}% | "
            f"Provider mix: {result['provider_mix']} | "
            f"p50 {result['latency_ms_p50']}ms p95 {result['latency_ms_p95']}ms",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
