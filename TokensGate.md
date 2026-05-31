# TokensGate — Codebase Map

> **For Claude:** Read this file before accessing any `.py` file in TokensGate.
> It gives you the full picture of what each file does, what's inside it, and whether you need to open it for a given task.
> Last updated: 2026-05-31 (Phase 4: doc sync — all mismatches resolved)

---

## Project State

| Phase | Status | Summary |
|-------|--------|---------|
| Phase 1 — Foundation | ✅ Complete | FastAPI skeleton, Redis integration, token counting, cost estimation |
| Phase 2 — Core Logic | ✅ Complete | SHA256 prompt cache, sliding-window rate limiter, cost-aware router, O(1) metrics |
| Phase 2.5 — Rate Limiter Fix | ✅ Complete | Rewrote fixed-window limiter as Redis ZSET sliding-window log |
| Phase 3 — Fault-Tolerant Egress | ✅ Complete | Circuit breaker (rolling window, Redis-backed), Ollama failover provider |
| Phase 4 — Polish | 🔄 In Progress | Live test ✅ · Benchmark ✅ · Doc sync ✅ · Resume bullet ✅ · Dashboard 🔜 |

**Test count:** 62 passing in 0.13s  
**Version:** `0.3.0`

---

## Entry Points

### `main.py`
- **What it is:** FastAPI application factory — start here for any app-boot question
- **Key contents:**
  - `lifespan()` async context manager (startup/shutdown) — replaced deprecated `@on_event`
  - `create_app()` returns the configured `FastAPI` instance
  - Startup logs: Redis ping, CB config, Ollama config
  - Imports from `app/api.py` for all route registration
- **When to read:** app startup issues, lifespan/boot behavior, top-level app config

---

## `app/` Package

### `app/__init__.py`
- **What it is:** Package marker + version
- **Key contents:** `__version__ = "0.3.0"`, module docstring
- **When to read:** version bumps only — almost never needed

---

### `app/config.py`
- **What it is:** All environment-variable config in one place — single source of truth
- **Key contents:**
  - **Anthropic:** `CLAUDE_API_KEY`, `CHEAP_MODEL` (`claude-haiku-4-5-20251001`), `EXPENSIVE_MODEL` (`claude-sonnet-4-5-20250929`)
  - **Redis:** `REDIS_URL`
  - **Rate limits:** `RATE_LIMIT_REQUESTS`, `RATE_LIMIT_TOKENS` (per minute, per client)
  - **Routing:** `ROUTE_CHEAP_MAX_TOKENS` (500 token threshold for Haiku vs Sonnet)
  - **Circuit breaker (Phase 3):** `CIRCUIT_BREAKER_ENABLED`, `CB_FAILURE_THRESHOLD` (5), `CB_WINDOW_SECONDS` (30), `CB_COOLDOWN_SECONDS` (60)
  - **Ollama (Phase 3):** `OLLAMA_BASE_URL`, `OLLAMA_MODEL` (`llama3.2:1b`), `OLLAMA_TIMEOUT_SECONDS`, `OLLAMA_FALLBACK_ENABLED`
- **When to read:** adding/changing env vars, debugging wrong config values

---

### `app/deps.py`
- **What it is:** Shared dependency singletons — Redis client and Anthropic client
- **Key contents:**
  - `redis_client` — initialized from `REDIS_URL`, `None` if connection fails (fail-open)
  - `anthropic_client` — initialized from `CLAUDE_API_KEY`, `None` if key missing
  - `logger` — structured logger used across all modules
- **When to read:** connection issues, client init, test monkeypatching (tests patch `deps.anthropic_client` and `deps.redis_client`)
- **Important:** Provider code resolves `anthropic_client` at call time (not import time) so monkeypatches work

---

### `app/models.py`
- **What it is:** Pydantic request/response models
- **Key contents:**
  - `Message` — `{role: str, content: str}`
  - `ChatCompletionRequest` — `{model, messages, max_tokens, temperature, stream, ...}`
  - `ChatCompletionResponse` — OpenAI-compatible shape
- **When to read:** request validation errors, adding new request fields

---

### `app/tokenizer.py`
- **What it is:** Token counting using tiktoken (OpenAI BPE — estimate only)
- **Key contents:**
  - `count_tokens(messages)` → int — pre-call estimate for routing/rate decisions
  - Uses `cl100k_base` encoding (closest to Claude)
  - **Not used for billing** — billing uses `response.usage` from Anthropic (authoritative)
- **When to read:** token counting logic, routing threshold changes

---

### `app/pricing.py`
- **What it is:** Per-model pricing table for cost estimation
- **Key contents:**
  - `PRICING` dict — input/output cost per token for Haiku 4.5, Sonnet 4.5, Opus models
  - `estimate_cost(model, input_tokens, output_tokens)` → `{input_cost, output_cost, total_cost}`
  - Ollama cost is always `$0.0` (local inference, no API spend)
- **When to read:** cost calculation bugs, adding new model pricing

---

### `app/cache.py`
- **What it is:** Deterministic SHA256 prompt cache in Redis
- **Key contents:**
  - `compute_cache_key(model, temperature, max_tokens, messages)` → SHA256 hex string
  - `get_cached_response(key)` → `dict | None`
  - `set_cached_response(key, value, ttl=86400)` — 24h TTL
  - Hit/miss counters: `cache:hits`, `cache:misses`
  - **Only Anthropic responses are cached** — Ollama fallback results are NOT written to cache
- **When to read:** cache key design, TTL changes, cache hit/miss debugging

---

### `app/rate_limit.py`
- **What it is:** Sliding-window rate limiter per client (Redis ZSET log)
- **Key contents:**
  - `_now_ms()` — clock shim, monkeypatchable for virtual-time tests
  - `client_id_from_request(request)` → `str` — extracts `X-Client-ID` header → bearer token → IP fallback
  - `check_and_increment(client_id, token_count)` → `RateLimitResult` — checks limits and increments if allowed; result fields: `.allowed`, `.reason`, `.limit_requests`, `.limit_tokens`, `.request_count`, `.token_count`, `.retry_after_seconds`
  - ZSET key: `rl:reqs:{client_id}` — score = ms timestamp, member = `{uuid}:{token_count}`
  - Tracks **requests/min** AND **tokens/min** independently
  - Rejected requests do NOT count against the bucket
  - Returns `Retry-After` based on oldest in-window entry expiry
  - Fail-open on Redis errors
- **When to read:** rate limit bugs, window size changes, retry-after header math

---

### `app/router.py`
- **What it is:** Cost-aware model selection
- **Key contents:**
  - `choose_model(request, body_model, estimated_input_tokens)` → `RoutingDecision` dataclass: `{model, strategy, reason, threshold, estimated_input_tokens}`
  - Strategies: `auto` (default), `cheap` (force Haiku), `expensive` (force Sonnet), `explicit` (use request.model as-is), `auto_fallback` (explicit header sent but no model in body — falls back to auto sizing, label makes the fallback visible in response)
  - Strategy read from `X-Route-Strategy` header
  - Auto threshold: Haiku if `estimated_input_tokens < ROUTER_THRESHOLD_TOKENS` (500), else Sonnet
- **When to read:** routing logic, adding new strategies, threshold tuning

---

### `app/metrics.py`
- **What it is:** O(1) counter-based aggregated metrics + recent-request ring buffer
- **Key contents:**
  - `log_request_metrics(*, request_id, client, model, input_tokens, output_tokens, response_time_ms, cache_hit, routing_strategy, status, error)` — INCRBY on 6 counters: `requests`, `errors`, `input_tokens`, `output_tokens`, `cost_micros` (USD×1e6 — Redis can't INCRBY floats), `response_time_ms`; appends JSON record to ring buffer
  - `get_aggregate_metrics()` → dict of aggregated totals (divides `cost_micros / 1e6` on read)
  - `get_recent_requests(limit=20)` → list of recent request records; guards against `limit <= 0` explicitly (Redis `lrange(0, -1)` returns everything — off-by-one trap)
  - `reset_metrics()` — test helper, clears all counters and ring buffer; not exposed via HTTP
  - Ring buffer: `LPUSH metrics:recent` + `LTRIM` to last 200 entries
  - No `KEYS *` — production-safe
- **When to read:** `/metrics` endpoint issues, adding new counters

---

### `app/circuit_breaker.py` ⭐ Phase 3
- **What it is:** Rolling-window circuit breaker state machine, Redis-backed, per-target
- **Key contents:**
  - `CircuitState` enum: `CLOSED`, `OPEN`, `HALF_OPEN`
  - `BreakerSnapshot` dataclass: `target, state, failures_in_window, opened_at_ms, cooldown_remaining_s` — **no `total_trips` field**; `total_trips` is fetched separately from Redis inside `get_all_snapshots()` and included only in its output dict
  - `_now_ms()` — clock shim (monkeypatchable for virtual-time tests)
  - **Redis keys per target:**
    - `cb:fails:{target}` — ZSET, score = ms timestamp (rolling window log)
    - `cb:state:{target}` — STR: `"CLOSED"` | `"OPEN"` | `"HALF_OPEN"`
    - `cb:opened_at:{target}` — STR: ms timestamp when circuit opened
    - `cb:totals:{target}:trips` — INT counter: lifetime trip count
  - `allow_request(target)` → `(bool, BreakerSnapshot)`:
    - OPEN + cooldown active → False (skip provider)
    - OPEN + cooldown expired → transition to HALF_OPEN → True (canary)
    - CLOSED or HALF_OPEN → True
  - `record_failure(target, status_code)`:
    - ZADD fail to ZSET, prune entries outside window, count remaining
    - HALF_OPEN → immediately OPEN (canary failed)
    - CLOSED → OPEN if `failures_in_window >= CB_FAILURE_THRESHOLD`
  - `record_success(target)`:
    - HALF_OPEN → CLOSED + clear failure ZSET (recovery)
    - CLOSED → no-op
  - `get_snapshot(target)` → `BreakerSnapshot` — read current state for a single target without mutating; used by `_response_headers` in `api.py` to populate the per-response CB state headers
  - `get_all_snapshots(targets)` → dict (includes `total_trips` pulled from Redis) — used by `/health` and `/metrics`
  - `reset(target)` — test helper, clears all CB Redis keys
- **When to read:** CB state transition bugs, cooldown/threshold changes, CB telemetry

---

### `app/providers.py` ⭐ Phase 3
- **What it is:** Provider abstraction + CB-aware failover orchestrator
- **Key contents:**
  - **Constants:** `ANTHROPIC_TARGET = "anthropic"`, `OLLAMA_TARGET = "ollama"`
  - `CompletionResult` dataclass: `text, input_tokens, output_tokens, model, provider, latency_ms, attempts: List[str]`
  - `ProviderError(Exception)`: `status_code, is_retryable, provider`
  - `_classify_anthropic_error(exc)` → `ProviderError` — maps SDK exceptions:
    - `APITimeoutError`, `APIConnectionError` → `is_retryable=True`
    - `APIStatusError` → retryable if `code >= 500` or `code == 429`
    - Unknown → retryable=True (safe default)
  - `AnthropicProvider.generate(messages, model, max_tokens, temperature)` → `CompletionResult`
    - Resolves `deps_mod.anthropic_client` at call time (monkeypatch-safe)
    - Raises `ProviderError(is_retryable=False)` if client is None
  - `OllamaProvider.generate(messages, model, max_tokens, temperature)` → `CompletionResult`
    - POSTs to `{base_url}/api/chat`
    - Handles: `Timeout` → retryable, `ConnectionError` → retryable, 5xx/429 → retryable, 4xx → not retryable
    - Parses: `message.content`, `prompt_eval_count` (input), `eval_count` (output)
  - **Module singletons:** `anthropic_provider`, `ollama_provider` (tests monkeypatch these)
  - `call_with_failover(messages, model, max_tokens, temperature)` → `CompletionResult`:
    1. If `anthropic_client is None` → skip Anthropic (`anthropic:not_configured`)
    2. Check Anthropic CB → if OPEN, skip (`anthropic:cb_open`)
    3. Try Anthropic → success: return; retryable fail: record_failure, fall through; non-retryable: raise immediately
    4. Check `OLLAMA_FALLBACK_ENABLED` — if False, raise 503
    5. Check Ollama CB → if OPEN, raise
    6. Try Ollama → success: return; fail: record_failure, raise combined error
    - `attempts` list tracks every leg: e.g. `["anthropic:error:503", "ollama:ok"]`
- **When to read:** failover logic, provider error handling, adding a new provider, CB integration

---

### `app/api.py` ⭐ Core
- **What it is:** All FastAPI route handlers — the main pipeline wiring all modules together
- **Key contents:**
  - `POST /v1/chat/completions` — full pipeline:
    1. Parse + validate request
    2. Identify client (`X-Client-ID` → bearer → IP)
    3. Count tokens (tokenizer)
    4. Route model (router)
    5. Rate check (rate_limit)
    6. Cache lookup
    7. **`prov.call_with_failover(...)`** — replaces direct Anthropic call
    8. Cache write (Anthropic responses only)
    9. Record metrics
    10. Return response with headers
  - `GET /health` — Redis ping + CB snapshots for both providers
  - `GET /metrics` — aggregated counters + CB snapshots
  - `_response_headers()` — builds all response headers:
    - `X-Cache`, `X-RateLimit-Remaining-*`, `X-TokensGate-Model`
    - Phase 3: `X-TokensGate-Provider`, `X-TokensGate-Fallback`, `X-TokensGate-Attempts`, `X-TokensGate-CB-Anthropic`, `X-TokensGate-CB-Ollama`
  - On `ProviderError`: returns 503 JSON with `error.type="upstream_unavailable"` + CB state
- **When to read:** request pipeline, response shape, header logic, error responses

---

## `tests/` Directory

### `tests/conftest.py`
- **What it is:** Shared pytest fixtures
- **Key contents:**
  - `fake_redis` fixture — `fakeredis.FakeRedis()` instance (no real Redis needed)
  - Monkeypatches `deps.redis_client`, `cache.redis_client`, `rate_limit.redis_client`, `metrics.redis_client`, `circuit_breaker.redis_client`
  - `client` fixture — `TestClient(app)` with fake Redis wired in
- **When to read:** adding new fixtures, fixture scope issues

### `tests/test_tokenizer.py` — 4 tests
- Token counting and per-message overhead

### `tests/test_cache.py` — 6 tests
- Cache key sensitivity (model/temperature/messages), hit/miss accounting

### `tests/test_rate_limit.py` — 10 tests
- Per-client limits, slow-drip regression, token axis, retry-after math, sliding window

### `tests/test_router.py` — 6 tests
- Auto threshold, forced strategies, explicit-model precedence

### `tests/test_circuit_breaker.py` — 11 tests
- All state transitions, rolling window decay, canary paths, reset, get_all_snapshots, trip counter
- Uses `virtual_clock` fixture (monkeypatches `cb._now_ms`) — no real sleeps

### `tests/test_providers.py` — 15 tests
- Ollama wire-level (monkeypatched `requests.post`)
- Anthropic happy path, no-client fatal, unknown-exception retryable
- All 7 failover branches: healthy, retryable failover, non-retryable short-circuit, both-down, CB-open, not-configured, fallback-disabled

### `tests/test_api.py` — 11 tests
- End-to-end: health, cache hit, routing, 429 on flood, metrics
- Phase 3: response headers, Ollama failover response, both-down 503, `/health` CB state

---

## Root-Level Files

### `benchmark_failover.py` ⭐ Phase 3
- **What it is:** 3-phase failover benchmark (mock + live modes)
- **Key contents:**
  - `_ToggleStub` — stub provider that flips healthy↔broken mid-run via `healthy` flag
  - Phase A: healthy baseline (Anthropic only)
  - Phase B: simulate Anthropic outage → measure detection latency, CB trip, steady-state Ollama
  - Phase C: restore Anthropic → measure cooldown + recovery to CLOSED
  - Metrics: `detection_latency_ms`, pre/post-trip p50, `recovery_ms`, `uptime_pct`
  - Live mode: hits running Docker stack via `httpx`, reports provider mix from `X-TokensGate-Provider`
  - Mock results: 100% uptime, 345ms detection, 53.9ms Ollama p50, 3.0s recovery
- **When to read:** failover performance testing, live outage simulation

### `benchmark.py`
- **What it is:** Phase 2 cache/routing benchmark
- **Key contents:**
  - `--mode=mock` — fakeredis + stubbed Anthropic, fast, deterministic
  - `--mode=live` — real Docker Compose stack + Claude API
  - Live results: 94.97% cache hit rate, 2.88ms p50, $0.42 saved / $0.44 baseline
- **When to read:** cache hit rate testing, cost savings validation

### `docker-compose.yml`
- **What it is:** Container orchestration (gateway + Redis)
- **Key contents:** gateway service, redis service, all env vars with `${VAR:-default}` syntax including Phase 3 CB/Ollama vars
- **When to read:** Docker startup issues, env var defaults

### `Dockerfile`
- **What it is:** Gateway container build — Python 3.11 slim
- **When to read:** dependency or Python version issues

### `requirements.txt`
- **What it is:** Python dependencies
- **Key packages:** `fastapi`, `uvicorn`, `anthropic>=0.40.0`, `redis`, `tiktoken`, `requests`, `httpx`
- **When to read:** dependency conflicts, adding new packages

### `.env`
- **What it is:** Template env file with placeholder values — **never has real secrets**
- **Real secrets go in `.env.local`** (gitignored)
- **When to read:** checking default values or env var names

---

## Quick Decision Guide

| Task | Files to read |
|------|---------------|
| Debug a 503 failover | `app/providers.py`, `app/circuit_breaker.py` |
| Debug wrong model routing | `app/router.py`, `app/config.py` |
| Debug rate limit not triggering | `app/rate_limit.py` |
| Debug cache miss when hit expected | `app/cache.py` |
| Debug wrong cost in response | `app/pricing.py`, `app/api.py` |
| Add a new provider | `app/providers.py` (add Provider class + update `call_with_failover`) |
| Change CB threshold/window | `app/config.py`, `.env` |
| Add a new API endpoint | `app/api.py` |
| Debug app startup failure | `main.py`, `app/deps.py` |
| Run tests | `tests/conftest.py` + relevant `test_*.py` |
