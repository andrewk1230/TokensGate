"""Synthetic benchmark for TokensGate.

Two modes:
  --mode=mock  (default)  stubbed Anthropic + fakeredis. Fast, free, deterministic.
                          Proves the cache + router pipeline works end-to-end.
  --mode=live             real Anthropic API + real Redis. Burns API credits.
                          Use to capture the real resume number.

Usage:
    python benchmark.py --mode=mock --requests=200 --unique=10
    python benchmark.py --mode=live --requests=50 --unique=5 \
        --base-url=http://localhost:8000

Output:
    - Total requests, cache hit rate, total $ spent, p50/p95 latency
    - Estimated $ saved vs. the no-cache baseline
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import time
from types import SimpleNamespace

# Static prompt pool — keep small so we get cache hits even at low request counts.
PROMPT_POOL = [
    "Summarize the theory of relativity in one sentence.",
    "Write a haiku about distributed systems.",
    "Explain CAP theorem like I'm a sophomore CS student.",
    "What's the difference between a process and a thread?",
    "List three benefits of using Redis as a cache.",
    "Describe the circuit breaker pattern.",
    "How does SHA256 differ from MD5?",
    "Explain token-bucket rate limiting.",
    "Why is fixed-window rate limiting weaker than sliding-window?",
    "What is the purpose of an API gateway?",
]


def run_mock(requests: int, unique: int, seed: int) -> dict:
    """Run the gateway in-process with a stubbed Anthropic client.

    Cache hits are real (we use fakeredis); Anthropic calls return canned text.
    """
    os.environ.setdefault("CLAUDE_API_KEY", "mock-key")
    os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
    os.environ.setdefault("RATE_LIMIT_REQUESTS_PER_MIN", str(requests + 10))
    os.environ.setdefault("RATE_LIMIT_TOKENS_PER_MIN", "10000000")

    import fakeredis
    from fastapi.testclient import TestClient

    from app import api as api_mod
    from app import cache as cache_mod
    from app import deps as deps_mod
    from app import metrics as metrics_mod
    from app import rate_limit as rl_mod

    # Wire fakeredis everywhere
    fake = fakeredis.FakeRedis(decode_responses=True)
    for mod in (deps_mod, cache_mod, rl_mod, metrics_mod):
        mod.redis_client = fake

    # Stub Anthropic
    class _StubMessages:
        def create(self, **kwargs):  # noqa: ANN001
            text = "[stubbed response]"
            # Simulate realistic token counts based on the prompt
            input_tokens = sum(len(m["content"].split()) for m in kwargs["messages"]) * 2
            return SimpleNamespace(
                content=[SimpleNamespace(text=text)],
                usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=50),
            )

    stub = SimpleNamespace(messages=_StubMessages())
    deps_mod.anthropic_client = stub
    api_mod.anthropic_client = stub

    from main import app
    client = TestClient(app)

    rng = random.Random(seed)
    pool = PROMPT_POOL[: max(1, min(unique, len(PROMPT_POOL)))]

    latencies = []
    hits = 0
    misses = 0
    statuses = {}

    for i in range(requests):
        prompt = rng.choice(pool)
        t0 = time.time()
        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": prompt}]},
            headers={"X-Client-ID": "bench"},
        )
        latencies.append((time.time() - t0) * 1000)
        statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
        if r.status_code == 200:
            if r.headers.get("X-Cache") == "HIT":
                hits += 1
            else:
                misses += 1

    metrics = client.get("/metrics").json()
    return _summarize(requests, hits, misses, latencies, statuses, metrics, mode="mock")


def run_live(requests: int, unique: int, base_url: str, seed: int) -> dict:
    """Hit a running gateway via HTTP. Burns real API credits.

    Uses httpx (already a hard dep of fastapi/anthropic) so this works
    even outside the venv as long as the gateway's deps are installed.
    """
    try:
        import httpx
    except ImportError:
        sys.exit(
            "ERROR: httpx not installed. Run inside the project venv:\n"
            "    source .venv/bin/activate && python benchmark.py --mode=live\n"
            "Or install httpx system-wide:\n"
            "    pip3 install httpx"
        )

    rng = random.Random(seed)
    pool = PROMPT_POOL[: max(1, min(unique, len(PROMPT_POOL)))]

    latencies = []
    hits = 0
    misses = 0
    statuses = {}

    with httpx.Client(base_url=base_url, timeout=60.0) as client:
        # Probe first so we fail fast with a clear error if the gateway isn't up.
        try:
            health = client.get("/health")
            health.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            sys.exit(
                f"ERROR: gateway not reachable at {base_url} ({exc}).\n"
                f"Start it first:\n"
                f"    docker compose up -d\n"
                f"Then re-run this benchmark."
            )

        for i in range(requests):
            prompt = rng.choice(pool)
            t0 = time.time()
            try:
                r = client.post(
                    "/v1/chat/completions",
                    json={"messages": [{"role": "user", "content": prompt}]},
                    headers={"X-Client-ID": "bench"},
                )
            except httpx.HTTPError as exc:
                latencies.append((time.time() - t0) * 1000)
                statuses["network_error"] = statuses.get("network_error", 0) + 1
                print(f"  [{i}] network error: {exc}", file=sys.stderr)
                continue

            latencies.append((time.time() - t0) * 1000)
            statuses[r.status_code] = statuses.get(r.status_code, 0) + 1
            if r.status_code == 200:
                if r.headers.get("X-Cache") == "HIT":
                    hits += 1
                else:
                    misses += 1
            elif r.status_code == 429:
                # Don't burn time hammering a rate-limited bucket.
                retry = int(r.headers.get("Retry-After", "1"))
                print(f"  [{i}] 429 — sleeping {retry}s", file=sys.stderr)
                time.sleep(retry)

        metrics = client.get("/metrics").json()
    return _summarize(requests, hits, misses, latencies, statuses, metrics, mode="live")


def _summarize(requests, hits, misses, latencies, statuses, metrics, mode) -> dict:
    total_ok = hits + misses
    hit_rate = hits / total_ok if total_ok else 0.0

    # Spent = what we actually paid (cache hits cost $0 in upstream).
    spent = metrics.get("total_cost", 0.0)
    # Baseline = what we WOULD have paid without the cache: extrapolate misses.
    avg_cost_per_miss = (spent / misses) if misses else 0.0
    baseline = avg_cost_per_miss * total_ok
    saved = baseline - spent
    savings_pct = (saved / baseline) if baseline else 0.0

    p50 = statistics.median(latencies) if latencies else 0.0
    p95 = (
        sorted(latencies)[int(len(latencies) * 0.95) - 1]
        if len(latencies) >= 20 else max(latencies, default=0.0)
    )

    return {
        "mode": mode,
        "requests_attempted": requests,
        "requests_ok": total_ok,
        "status_codes": statuses,
        "cache_hits": hits,
        "cache_misses": misses,
        "cache_hit_rate": round(hit_rate, 4),
        "spent_usd": round(spent, 6),
        "baseline_usd_no_cache": round(baseline, 6),
        "saved_usd": round(saved, 6),
        "savings_pct": round(savings_pct, 4),
        "latency_p50_ms": round(p50, 2),
        "latency_p95_ms": round(p95, 2),
        "metrics_snapshot": metrics,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["mock", "live"], default="mock")
    p.add_argument("--requests", type=int, default=200)
    p.add_argument("--unique", type=int, default=10)
    p.add_argument("--base-url", default="http://localhost:8000")
    p.add_argument("--seed", type=int, default=42)
    args = p.parse_args()

    if args.mode == "mock":
        result = run_mock(args.requests, args.unique, args.seed)
    else:
        result = run_live(args.requests, args.unique, args.base_url, args.seed)

    print(json.dumps(result, indent=2))

    # Resume-line preview
    print("\n--- Resume-line preview ---")
    print(
        f"Cache hit rate: {result['cache_hit_rate']*100:.1f}%  |  "
        f"Cost saved: ${result['saved_usd']:.4f} ({result['savings_pct']*100:.1f}%)  |  "
        f"p50 {result['latency_p50_ms']:.1f}ms, p95 {result['latency_p95_ms']:.1f}ms"
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
