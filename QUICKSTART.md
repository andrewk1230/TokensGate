# TokensGate — 5-Minute Quick Start

## 🚀 Get Running in 5 Steps

### Step 1: Clone/Navigate to TokensGate

```bash
cd "00 Notes/Coding/Projects/TokensGate"
```

### Step 2: Copy Environment Template

```bash
cp .env.example .env.local
```

### Step 3: Add Your Claude API Key

Edit `.env.local`:
```
CLAUDE_API_KEY=sk-ant-v1-YOUR-KEY-HERE
```

Get your key from: https://console.anthropic.com/keys

### Step 4: Start Docker Compose

```bash
docker-compose up
```

Wait for:
```
redis    | * Ready to accept connections
gateway  | Uvicorn running on http://0.0.0.0:8000
```

### Step 5: Test It

Open a new terminal:

```bash
# Health check
curl http://localhost:8000/health

# Send a chat message
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-haiku-20240307",
    "messages": [
      {"role": "user", "content": "Say hello!"}
    ]
  }' | jq .
```

You should see a response with token counts and cost breakdown! 🎉

---

## 📊 View Your Metrics

```bash
curl http://localhost:8000/metrics | jq .
```

---

## 🛑 Stop Everything

```bash
# In the terminal running docker-compose
Ctrl+C

# Or from another terminal
docker-compose down
```

---

## 📁 What You Just Created

```
TokensGate/
├── main.py                    ← Gateway logic (FastAPI)
├── docker-compose.yml         ← Run Redis + Gateway together
├── Dockerfile                 ← Container definition
├── requirements.txt           ← Python dependencies
├── .env.local                 ← Your secrets (DO NOT COMMIT)
└── README.md                  ← Full documentation
```

---

## 🧪 Test Different Requests

**Test 1: Simple query**
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-haiku-20240307",
    "messages": [{"role": "user", "content": "What is the capital of France?"}],
    "max_tokens": 100
  }' | jq .
```

**Test 2: Longer context**
```bash
curl -X POST http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "claude-3-haiku-20240307",
    "messages": [
      {"role": "system", "content": "You are a helpful assistant."},
      {"role": "user", "content": "Explain quantum computing in 3 sentences."}
    ],
    "max_tokens": 200
  }' | jq .
```

**Test 3: Check metrics**
```bash
curl http://localhost:8000/metrics | jq .
```

---

## 📋 Current Phase (Week 1-2)

✅ FastAPI gateway running
✅ Redis connected
✅ Token counting working
✅ Cost estimation visible
✅ Request logging in place

---

## 🎯 Next Milestones

| Week | Task | Status |
|------|------|--------|
| 1-2 | Foundation (current) | 🟢 In Progress |
| 3-4 | Prompt caching + rate limiting | ⬜ Upcoming |
| 5-6 | Circuit breaker + failover | ⬜ Upcoming |
| 7-8 | Benchmarking + monitoring | ⬜ Upcoming |

---

## 💡 Tips

- **See logs in real-time:** `docker-compose logs -f gateway`
- **Check Redis:** `docker-compose exec redis redis-cli`
- **Code hot-reloads:** Edit `main.py` → changes appear instantly
- **Reset data:** `docker-compose exec redis redis-cli FLUSHDB`

---

## ⚠️ Troubleshooting

| Problem | Fix |
|---------|-----|
| `docker-compose: command not found` | Install Docker Desktop |
| `Port 6379 already in use` | Change port in `docker-compose.yml` |
| `401 Unauthorized` | Check `CLAUDE_API_KEY` in `.env.local` |
| `ConnectionError to Redis` | Run `docker-compose up` first |

---

## 📚 Full Documentation

See `README.md` for:
- Architecture overview
- All API endpoints
- Environment variables
- Development guide
- Cost model details

See `Summer proj.md` for:
- Full technical specification
- 8-week execution plan
- Success metrics
- Learning objectives

---

## 🚀 Ready?

You now have a working gateway that:
- ✅ Accepts OpenAI-compatible requests
- ✅ Counts tokens accurately
- ✅ Forwards to Claude API
- ✅ Tracks costs
- ✅ Stores metrics in Redis

**Next:** Move to Phase 2 (weeks 3-4) to add prompt caching and rate limiting.

Questions? Check `README.md` or the full spec in `Summer proj.md`.
