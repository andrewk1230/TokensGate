# TokensGate 🚀

Intelligent LLM API Gateway with Token Optimization & Fault Tolerance

**An reverse-proxy API gateway positioned between client applications and Claude API.**

Reduces LLM API expenditures via token compression and caching while guaranteeing 100% application uptime through automated fault detection and circuit-breaking failovers.

---

## Getting Started (from GitHub)

```bash
# 1. Clone the repo
git clone https://github.com/andrewk1230/TokensGate.git
cd TokensGate

# 2. Copy the env template and add your Anthropic key
cp .env .env.local
# Open .env.local and set:  CLAUDE_API_KEY=YOUR_API_KEY

# 3. Start everything with Docker Compose
docker-compose up

# 4. Verify it's running
curl http://localhost:8000/health

# 5. Open the monitoring dashboard in your browser
open http://localhost:8000/dashboard   # macOS
# or xdg-open http://localhost:8000/dashboard  (Linux)
```

> **No Python install needed** — the gateway runs inside Docker. If you want to run tests locally, see [Running Tests Locally](#running-tests-locally).

---

## Quick Start (5 minutes)

### Prerequisites
- Docker & Docker Compose installed ([install here](https://docs.docker.com/get-docker/))
- Claude API key ([get here](https://console.anthropic.com))
- Optional: Ollama installed ([install here](https://ollama.ai)) for fallback testing

### Step 1: Set Up Environment Variables

```bash
cd TokensGate
cp .env.example .env.local
```

Edit `.env.local` and add your Claude API key:
```
CLAUDE_API_KEY=your-actual-key-here
```

### Step 2: Start the Gateway with Docker Compose

```bash
docker-compose up
```

You should see:
```
redis    | Ready to accept connections
gateway  | Uvicorn running on http://0.0.0.0:8000
```

### Step 3: Test the Gateway

In a new terminal:

```bash
# Health check
curl http://localhost:8000/health

# Send a chat completion request
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-haiku-20240307",
    "messages": [
      {"role": "user", "content": "What is 2+2?"}
    ],
    "max_tokens": 100
  }' | jq .
```

### Step 4: View Metrics

```bash
curl http://localhost:8000/metrics | jq .
```

### Step 5: Open the Monitoring Dashboard

Open your browser and visit:

```
http://localhost:8000/dashboard
```

The dashboard is a self-contained HTML page (no external dependencies) that shows:
- **System Status** — Redis, Anthropic API, and Gateway health
- **Circuit Breakers** — state (CLOSED / OPEN / HALF_OPEN), failure counts, cooldown timers
- **Request Metrics** — total requests, error rate, avg latency, total cost
- **Cache Performance** — hit rate (color-coded), hits/misses count
- **Token Usage** — input, output, and total tokens
- **Recent Requests** — last 20 requests with timing, model, cache, and status

> The page auto-refreshes every 10 seconds.

---

## Project Structure

```
TokensGate/
├── main.py                    # FastAPI gateway application
├── docker-compose.yml         # Container orchestration
├── Dockerfile                 # FastAPI container definition
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variables template
├── .gitignore                 # Git ignore rules
├── README.md                  # This file
└── Summer proj.md             # Project specification & execution plan
```

---

## Architecture

```
┌─────────────┐
│   Client    │
└──────┬──────┘
       │ POST /v1/chat/completions
       ▼
┌────────────────────────────────────────────────────────────┐
│   Layer 1: Ingestion & Optimization                        │
│   • Token estimate (tiktoken)                              │
│   • Deterministic SHA256 prompt cache (Redis)              │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│   Layer 2: Traffic & Rate Management                       │
│   • Sliding-window rate limiter (Redis ZSET)               │
│   • Cost-aware router (Haiku ↔ Sonnet)                     │
└──────────────────────┬─────────────────────────────────────┘
                       ▼
┌────────────────────────────────────────────────────────────┐
│   Layer 3: Fault-Tolerant Egress                           │
│   • Circuit breaker (rolling-window, per-target)           │
│   • Primary: Anthropic Claude                              │
│   • Fallback: Ollama (local)                               │
└────────┬───────────────────────┬───────────────────────────┘
         │                       │
         ▼                       ▼
   ┌──────────┐            ┌──────────┐
   │ Claude   │            │  Ollama  │
   │   API    │  (failover)│  (local) │
   └──────────┘            └──────────┘
```

---

## Features

### Foundation 
- **OpenAI-compatible API** at `/v1/chat/completions`
- **Token counting** via `tiktoken` (estimates only — billing uses `response.usage` from Anthropic)
- **Cost estimation** with per-model pricing table
- **Redis integration** for caching, metrics, rate limiting
- **Structured logging** with request IDs

### Core Logic 
- **Deterministic SHA256 prompt cache** — keyed on (model, temperature, max_tokens, messages); 24h TTL
- **Sliding-window rate limiter** — Redis ZSET log; tracks both requests/min AND tokens/min independently
- **Cost-aware router** — `X-Route-Strategy: auto|cheap|expensive|explicit`, Haiku <500 tokens, Sonnet ≥500
- **O(1) counter-based metrics** — no `KEYS *` foot-guns
- **Response headers** — `X-Cache`, `X-RateLimit-Remaining-*`, `X-TokensGate-*`

### Fault-Tolerant Egress 
- **Circuit breaker (rolling window)** — per-target state machine (CLOSED → OPEN → HALF_OPEN); trips at 5 failures in any 30s window; 60s cooldown; canary recovery
- **Ollama fallback provider** — when Anthropic's circuit is OPEN or returns a retryable error (5xx / 429 / timeout), traffic auto-fails-over to a local Ollama instance ($0 cost, no API credits burned)
- **Persistent CB state in Redis** — survives gateway restarts and is shared across replicas
- **Failure classification** — 4xx auth/validation errors do NOT trip the breaker (they're caller bugs, not provider health issues)
- **Failover headers** — `X-TokensGate-Provider`, `X-TokensGate-Fallback`, `X-TokensGate-Attempts`, `X-TokensGate-CB-Anthropic`, `X-TokensGate-CB-Ollama`
- **CB telemetry** in `/health` and `/metrics`

---

## API Reference

### `POST /v1/chat/completions`

**Request:**
```json
{
  "model": "claude-3-haiku-20240307",
  "messages": [
    {"role": "user", "content": "Hello!"}
  ],
  "max_tokens": 1024,
  "temperature": 0.7
}
```

**Response:**
```json
{
  "id": "chatcmpl-abc123",
  "object": "chat.completion",
  "created": 1234567890,
  "model": "claude-3-haiku-20240307",
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 50,
    "total_tokens": 60
  },
  "cost": {
    "input_tokens": 10,
    "output_tokens": 50,
    "input_cost": 0.00003,
    "output_cost": 0.00075,
    "total_cost": 0.00078
  },
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you today?"
      },
      "finish_reason": "stop"
    }
  ]
}
```

### `GET /health`

Returns gateway health status:
```json
{
  "status": "healthy",
  "environment": "development",
  "redis": "ok",
  "anthropic": "ready",
  "circuit_breakers": {
    "anthropic": {"state": "closed", "failures_in_window": 0, "total_trips": 0, ...},
    "ollama":    {"state": "closed", "failures_in_window": 0, "total_trips": 0, ...}
  },
  "timestamp": "2024-05-20T15:30:45.123456"
}
```

### `GET /metrics`

Aggregated metrics from Redis:
```json
{
  "total_requests": 42,
  "total_input_tokens": 5000,
  "total_output_tokens": 2500,
  "total_cost": 0.075,
  "average_response_time_ms": 1250.5,
  "cache": {"hits": 38, "misses": 4, "hit_rate": 0.904, "enabled": true},
  "circuit_breakers": { ... }
}
```

### `GET /dashboard`

Self-contained HTML monitoring page. Open in any browser — no login required.

- Auto-refreshes every 10 seconds
- Shows system status, circuit breaker state, request metrics, cache performance, token usage, and a live request log
- Works fully offline (no external fonts, icons, or CDN dependencies)

---

## Development

### Accessing Logs

```bash
# Watch live logs
docker-compose logs -f gateway

# View Redis logs
docker-compose logs redis
```

### Resetting Data

```bash
# Clear Redis cache
redis-cli FLUSHDB

# Or via Docker
docker-compose exec redis redis-cli FLUSHDB
```

### Restarting Services

```bash
# Restart gateway (code changes auto-reload)
docker-compose restart gateway

# Restart Redis
docker-compose restart redis

# Restart everything
docker-compose down && docker-compose up
```

### Running Tests Locally

```bash
# Install all dependencies (Python 3.9+ required)
pip install -r requirements.txt

# Run the full test suite (63 tests, no real Redis or API key needed)
pytest tests/ -v

# Run a single file
pytest tests/test_api.py -v
```

> Tests use `fakeredis` — no running Redis required. The Anthropic client is stubbed, so no API credits are spent.

---

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `CLAUDE_API_KEY` | ✓ Yes | — | Anthropic API key |
| `REDIS_URL` | No | `redis://localhost:6379` | Redis connection URL |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (DEBUG / INFO / WARNING / ERROR) |
| `ENVIRONMENT` | No | `development` | Shown as a badge on the dashboard |
| `CHEAP_MODEL` | No | `claude-haiku-4-5-20251001` | Model used for short prompts (< 500 tokens) |
| `EXPENSIVE_MODEL` | No | `claude-sonnet-4-5-20250929` | Model used for long prompts (≥ 500 tokens) |
| `RATE_LIMIT_REQUESTS_PER_MIN` | No | `100` | Max requests per client per minute |
| `RATE_LIMIT_TOKENS_PER_MIN` | No | `100000` | Max tokens per client per minute |
| `ROUTER_THRESHOLD_TOKENS` | No | `500` | Token count that switches Haiku → Sonnet |
| `CIRCUIT_BREAKER_ENABLED` | No | `true` | Enable/disable the circuit breaker |
| `CB_FAILURE_THRESHOLD` | No | `5` | Failures in window before circuit opens |
| `CB_WINDOW_SECONDS` | No | `30` | Rolling failure-count window (seconds) |
| `CB_COOLDOWN_SECONDS` | No | `60` | How long circuit stays OPEN before half-open probe |
| `OLLAMA_BASE_URL` | No | `http://host.docker.internal:11434` | Ollama server URL (local fallback) |
| `OLLAMA_MODEL` | No | `llama3.2:1b` | Ollama model to use for fallback completions |
| `OLLAMA_FALLBACK_ENABLED` | No | `true` | Allow failover to Ollama when Anthropic is down |

---

## Ollama Fallback Setup

Phase 3 adds a local Ollama provider as fallback. To enable:

```bash
# 1. Install Ollama → https://ollama.ai
# 2. Pull a small model for fast fallback
ollama pull llama3.2:1b

# 3. Start Ollama (default port 11434)
ollama serve

# 4. Verify the gateway sees it (after docker-compose up)
curl http://localhost:8000/health | jq '.circuit_breakers'
```

When Anthropic's circuit OPENs (5+ failures in 30s), the next request will route to Ollama automatically. You'll see this in the response headers:

```
X-TokensGate-Provider: ollama
X-TokensGate-Fallback: true
X-TokensGate-Attempts: anthropic:error:503,ollama:ok
X-TokensGate-CB-Anthropic: open
```

To simulate an Anthropic outage for testing, point `CLAUDE_API_KEY` at a bogus value or unplug your network — the gateway will trip its breaker after 5 retryable failures and start serving from Ollama for the cooldown duration.

---

## Troubleshooting

### Docker Issues

**Problem:** `docker-compose: command not found`
- Solution: Install Docker Desktop or Docker + Docker Compose separately

**Problem:** `Port 6379 already in use`
- Solution: Change Redis port in `docker-compose.yml` or kill existing Redis:
  ```bash
  lsof -ti:6379 | xargs kill -9
  ```

### Redis Connection Issues

**Problem:** `ConnectionError: Error 111 connecting to localhost:6379`
- Solution: Ensure Redis is running:
  ```bash
  docker-compose up redis
  ```

### Claude API Issues

**Problem:** `401 Unauthorized`
- Solution: Check your API key is correct in `.env.local`

**Problem:** `Rate limit exceeded`
- Solution: Wait before sending more requests, or upgrade your Claude API plan

### Port Already in Use

**Problem:** `Port 8000 already in use`
- Solution: Change gateway port in `docker-compose.yml` or kill process:
  ```bash
  lsof -ti:8000 | xargs kill -9
  ```

---

## Useful Commands

```bash
# Start everything
docker-compose up

# Start in background
docker-compose up -d

# Stop everything
docker-compose down

# View logs
docker-compose logs -f gateway

# Run command in container
docker-compose exec gateway bash

# Rebuild containers (after dependency changes)
docker-compose up --build

# Remove all volumes (full reset)
docker-compose down -v
```

---

## Performance Targets

| Metric | Target |
|--------|--------|
| Token compression ratio | 20-30% |
| Cache hit rate | 15-40% |
| Total cost reduction | 40-60% |
| Latency overhead | <50ms |
| Uptime during failover | 99.9% |

---

## Cost Model

**Baseline (No Gateway):**
- 1,000 requests/month to Claude
- Avg 2,500 input tokens per request
- Cost: ~$15/month

**With TokensGate:**
- Compression: 25% reduction
- Caching: 25% hit rate
- Estimated cost: ~$9.80/month
- **Savings: 35%**

---

## Resources

- [Claude API Docs](https://anthropic.com/docs)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Redis Documentation](https://redis.io/docs)
- [Tiktoken (Token Counting)](https://github.com/openai/tiktoken)
- [Docker Compose Docs](https://docs.docker.com/compose/)

---
