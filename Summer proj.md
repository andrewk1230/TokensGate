## **Project Overview**

* **Project Name:** TokensGate  
* **Role:** An intelligent, reverse-proxy API gateway positioned between client applications and downstream Large Language Model (LLM) providers.  
* **Core Objective:** To programmatically reduce LLM API expenditures via token compression and caching, while guaranteeing 100% application uptime through automated fault detection and circuit-breaking failovers.

---

## **System Architecture & Component Structure**

The gateway is designed as an asynchronous micro-pipeline. Every incoming request must sequentially pass through three decoupled structural layers before hitting an upstream AI model.

      \[ Client Request: POST /v1/chat/completions \]  
                           │  
                           ▼  
┌───────────────────────────────────────────────────────────┐  
│              LAYER 1: INGESTION & OPTIMIZATION            │  
│  \- Tokenizer Engine (tiktoken/tokenizers)                │  
│  \- NLP Fluff Stripper & Semantic Chunk Pruner             │  
│  \- Redis Semantic Prompt Cache Layer                      │  
└──────────────────────────┬────────────────────────────────┘  
                           │ (Optimized Context Payload)  
                           ▼  
┌───────────────────────────────────────────────────────────┐  
│              LAYER 2: TRAFFIC & RATE MANAGEMENT           │  
│  \- Redis Token-Bucket Rate Limiter                        │  
│  \- Cost-Aware Route Evaluator                             │  
└──────────────────────────┬────────────────────────────────┘  
                           │ (Target Provider Endpoint Selected)  
                           ▼  
┌───────────────────────────────────────────────────────────┐  
│              LAYER 3: FAULT-TOLERANT EGRESS               │  
│  \- Circuit Breaker State Machine (Closed/Open/Half-Open)   │  
│  \- Primary Provider Client \-\> \[ Failover Backup Client \]  │  
└──────────────────────────┬────────────────────────────────┘  
                           │  
                           ▼  
               \[ Upstream LLM Provider \]

### **1\. Ingestion & Optimization Layer**

This layer is responsible for decoding incoming JSON payloads, analyzing strings, and shrinking the token footprint before any network requests are fired out.

* **Token Metrology Engine:** Utilizes local BPE tokenizers (like OpenAI’s tiktoken or Hugging Face's tokenizers) to calculate precise input counts instantly.  
* **Algorithmic Compressor:** Runs text through string-manipulation filters to strip redundant spaces, markdown clutter, and grammatical stop-words that do not impact semantic comprehension for advanced models.  
* **Semantic Prompt Caching:** A **Redis**\-backed system that hashes incoming system prompts or long instruction contexts. If a match is found, it safely flags the request to leverage upstream provider prompt-caching features or local cache lookup schemes, preventing repetitive billing.

### **2\. Traffic & Rate Management Layer**

Once the payload is tightly optimized, this layer enforces security, isolation, and cost policies.

* **Token-Bucket Limiter:** A high-performance Redis script tracks individual client API keys, managing requests-per-minute (RPM) and tokens-per-minute (TPM) allocations dynamically to prevent server exhaustion.  
* **Cost-Aware Router:** A decision module that inspects the length of the optimized payload. If the prompt is small, it targets a highly efficient, low-cost model. If it exceeds a specific token threshold, it dynamically upgrades the route to a high-context model.

### **3\. Fault-Tolerant Egress Layer**

This layer safeguards system availability by monitoring the real-time success rates of external APIs.

* **Circuit Breaker Pattern:** A state machine running for each model provider:  
  * **CLOSED:** System runs normally; all traffic routes to the primary low-cost provider.  
  * **OPEN:** If error thresholds (e.g., three consecutive 503 Service Unavailable or 429 Rate Limit responses) are crossed, the circuit trips. Traffic is instantly diverted around the failing provider to a designated backup model.  
  * **HALF-OPEN:** After a timeout duration (e.g., 60 seconds), the gateway sends a small percentage of trial traffic to the primary provider to see if it has recovered. If successful, the circuit closes; if it fails, it re-opens.

---

## **Detailed Data Lifecycle Flow**

1. **Client POST:** The client application submits a standard OpenAI-compatible JSON completion request to your gateway.  
2. **Compression Stage:** The gateway intercepts the text body. It applies string compression, reducing a 2,500-token verbose prompt down to a crisp 1,700 tokens without losing meaning.  
3. **Rate Check:** The gateway verifies via Redis that the client has not exceeded their structural spending or request limits.  
4. **Health Check & Routing:** The gateway checks the state machine. The primary provider is marked healthy, so it builds the external HTTP payload.  
5. **Execution & Failover (If Triggered):** The gateway fires the compressed text to the primary provider. If the provider throws an immediate timeout or outage error, the **Circuit Breaker** trips, catches the exception, and immediately routes the exact same compressed payload to a backup provider instead.  
6. **Response & Logging:** The gateway streams or returns the final response JSON back to the user application, calculates the financial savings delta ($Tokens\_{Saved} \= Tokens\_{Original} \- Tokens\_{Compressed}$), and logs the performance metrics asynchronously to a telemetry database.

---

## **Recommended Tech Stack**

* **Gateway Framework:** **FastAPI (Python)** . *Why:* Offer exceptional non-blocking asynchronous event loops (async/await) designed to hold open lightweight web proxies under high traffic.  
* **Caching & State Broker:** **Redis**. *Why:* Used to handle distributed locking, state-tracking for the circuit breakers, client rate-limiting, and fast semantic prompt lookups.  
* **Model Execution/Testing Environment:** A local deployment using **Ollama** or **vLLM** running light, open-source models (like Llama-3 or Mistral) alongside fallback integrations with mock or real public developer APIs.  
* **Containerization & Testing:** **Docker** and **Docker-Compose** to cleanly isolate the gateway API, the Redis cluster, and local model nodes into a reproducible engineering system.

---

## **Why this Structure Succeeds on a Resume**

When you present this project to an interviewer, you aren't just presenting a simple script. You are proving mastery over **Enterprise Backend Patterns**:

* **You deal with systemic fragility:** Implementing a circuit breaker shows you understand that remote web services fail, and you know how to write software that self-heals under stress.  
* **You deal with resource constraints:** Showcasing string tokenization and Redis key-eviction mechanics proves you know how to minimize computing bottlenecks.  
* **You provide clear business metrics:** You can run a synthetic benchmarking script, simulate a 30% outage on a model provider, and explicitly state on your resume how many mock dollars your gateway saved in token overhead and downtime mitigation.

![][image1]

### **1\. Layer 1: Configurable Compression & Semantic Vector Caching**

To eliminate the risk of destroying codebase structural code or markdown logic, the ingestion engine inspects incoming headers for an optimization profile. If optimization is enabled, instead of doing a literal string match, it handles semantic similarity caching via text embeddings.

* **Header Check:** Looks for X-Sentinel-Optimize. If set to None, string stripping is bypassed entirely.  
* **Semantic Cache Pipeline:**  
  1. An incoming prompt arrives: *"Can you give me a summary of this document?"*  
  2. The gateway routes the text to a fast, cheap local or hosted embedding model to generate a vector representation.  
  3. The vector is queried against a vector database using **Cosine Similarity**:  
     $$\\text{Similarity} \= \\frac{\\mathbf{A} \\cdot \\mathbf{B}}{\\|\\mathbf{A}\\| \\|\\mathbf{B}\\|}$$  
  4. If a vector matches with a similarity threshold of $\\ge 0.95$, the system returns the cached completion payload immediately, completely bypassing the upstream LLM network call.

### **2\. Layer 2: Atomic Token-Bucket Rate Limiter (Redis Lua Script)**

Using standard distributed application code to check and then decrement rates creates race conditions under high concurrency. To guarantee precision, the rate limiter uses an atomic Redis Lua script. The entire operations block executes on the Redis instance as a single transaction.

Lua  
\-- keys\[1\]: Rate limit tracking key (e.g., rate:client\_12345)  
\-- ARGV\[1\]: Max bucket capacity (Tokens/Requests permitted)  
\-- ARGV\[2\]: Replenishment rate per second  
\-- ARGV\[3\]: Current timestamp (Unix epoch seconds)  
\-- ARGV\[4\]: Requested tokens to consume

local bucket \= redis.call('hgetall', KEYS\[1\])  
local last\_update \= tonumber(ARGV\[3\])  
local capacity \= tonumber(ARGV\[1\])  
local refill\_rate \= tonumber(ARGV\[2\])  
local requested \= tonumber(ARGV\[4\])

local tokens \= capacity  
local last\_touch \= last\_update

if \#bucket \> 0 then  
    for i \= 1, \#bucket, 2 do  
        if bucket\[i\] \== 'tokens' then tokens \= tonumber(bucket\[i+1\]) end  
        if bucket\[i\] \== 'last\_touch' then last\_touch \= tonumber(bucket\[i+1\]) end  
    end  
end

\-- Replenish tokens based on elapsed time delta  
local elapsed \= math.max(0, last\_update \- last\_touch)  
tokens \= math.min(capacity, tokens \+ (elapsed \* refill\_rate))

if tokens \>= requested then  
    tokens \= tokens \- requested  
    redis.call('hset', KEYS\[1\], 'tokens', tokens, 'last\_touch', last\_update)  
    return 1 \-- Allowed  
else  
    redis.call('hset', KEYS\[1\], 'tokens', tokens, 'last\_touch', last\_update)  
    return 0 \-- Rate Limited  
end

### **3\. Layer 3: Circuit Breaker State Machine & Stream Strategy**

The egress proxy encapsulates each downstream API target in an isolated state machine instance.

* **State Machine Transitions:**  
  * **CLOSED:** All backend traffic routes to the primary model provider. Every consecutive failed connection (HTTP 429, HTTP 503, or read timeout) increments a failure counter. If failures $\\ge 3$, the state shifts to **OPEN**.  
  * **OPEN:** Traffic completely avoids the primary provider. Requests are dynamically remapped to the backup target. A cooldown clock starts. Once the countdown expires (e.g., 60 seconds), the state shifts to **HALF-OPEN**.  
  * **HALF-OPEN:** A limited percentage of canary requests (e.g., 10%) are passed to the primary provider. If those canary calls return an HTTP 200 OK, the failure counter resets to 0, and the circuit gracefully switches back to **CLOSED**. If any canary call fails, the circuit switches right back to **OPEN**, resetting the cooldown window.

#### **Streaming Fallback Strategy**

For standard requests, fallback routing happens transparently mid-flight. For streaming contexts (stream: true), the gateway checks the provider's health state *before* negotiating the upstream connection chunk handshake. If the primary provider's circuit state trips while actively streaming data chunks down to the client, the proxy cannot safely re-stitch a backup stream mid-sentence without causing UI corruption. The gateway intercepts the broken stream channel and pipes down a clean, structured JSON gateway exception block containing the telemetry state info instead.

### **4\. Non-Blocking Telemetry & Financial Modeling**

To maintain ultra-low proxy response latencies, telemetry calculations run completely out-of-band. Once the payload response is dispatched to the client, metrics packets are dropped into an in-memory worker ring-buffer channel.

A decoupled background thread pool pools metrics from this queue and flushes them to Prometheus using the specific cost tracking equation:

$$\\text{Savings} \= (\\text{InputTokens}\_{\\text{Original}} \\times \\text{CostPerToken}\_{\\text{Primary}}) \- (\\text{InputTokens}\_{\\text{Compressed}} \\times \\text{CostPerToken}\_{\\text{Target}})$$  
This architecture guarantees that telemetry analytics engines never sit directly on the application's critical network path.

---

## **📋 Execution Progress Log**

### **Phase 1 — Foundation ✅ Complete**
- FastAPI skeleton with OpenAI-compatible `/v1/chat/completions` endpoint
- Token counting via `tiktoken` (estimates) + `response.usage` for billing math
- Cost estimation with per-model pricing table (Claude 4.x models)
- Redis integration for caching, metrics, rate limiting
- Structured logging with request IDs
- Docker + Docker Compose containerization

---

### **Phase 2 — Core Logic ✅ Complete**
- **Deterministic SHA256 prompt cache** — keyed on `(model, temperature, max_tokens, messages)`, 24h TTL
- **Sliding-window rate limiter** — Redis ZSET log, tracks requests/min AND tokens/min independently per client; Phase 2.5 fix replaced a fixed-window counter that had a slow-drip bypass
- **Cost-aware router** — `X-Route-Strategy: auto|cheap|expensive|explicit`; Haiku for <500 tokens, Sonnet for ≥500
- **O(1) counter-based metrics** — no `KEYS *` foot-guns; 200-entry ring buffer for recent requests
- **Response headers** — `X-Cache`, `X-RateLimit-Remaining-*`, `X-TokensGate-*`
- **33 tests passing in 0.09s** (fakeredis + stubbed Anthropic; no real deps needed for CI)

**Live-validated benchmark (200 requests, 10 unique prompts, real Claude API):**

| Metric | Result |
|--------|--------|
| Cache hit rate | **94.97%** |
| Cost spent | $0.022 |
| Baseline (no cache) | $0.437 |
| **Cost saved** | **$0.415 (94.97%)** |
| Latency p50 (cache hits) | **2.88ms** |
| Rate limiter | ✅ 429 returned on burst load |

---

### **Phase 3 — Fault-Tolerant Egress ✅ Complete (live test pending)**

**Architecture added:**
- `app/circuit_breaker.py` — Rolling-window CB state machine (CLOSED → OPEN → HALF_OPEN), Redis-backed ZSET, per-target (Anthropic + Ollama), persistent across restarts
- `app/providers.py` — Unified provider abstraction; CB-aware failover orchestrator; `CompletionResult` + `ProviderError` types
- `app/api.py` — Wired to `call_with_failover()`; Ollama-safe caching; Phase 3 response headers

**Configuration:** CB threshold = 5 failures / 30s window, 60s cooldown. All env-configurable.

**Failover policy:**
- 5xx / 429 / timeout → retryable → trips breaker → falls to Ollama
- 4xx auth/validation → non-retryable → surfaces immediately (Ollama can't fix a bad API key)
- `anthropic_client=None` → treated as CB-OPEN → falls straight to Ollama
- Ollama results NOT cached (prevents fallback responses poisoning 24h Anthropic cache)

**Phase 3 response headers:**
```
X-TokensGate-Provider: ollama
X-TokensGate-Fallback: true
X-TokensGate-Attempts: anthropic:error:503,ollama:ok
X-TokensGate-CB-Anthropic: open
X-TokensGate-CB-Ollama: closed
```

**Test suite:** 62/62 passing in 0.13s (30 new tests added in Phase 3)

**Mock benchmark (`benchmark_failover.py`):**

| Metric | Result |
|--------|--------|
| Uptime during outage | **100%** |
| Detection latency | **345ms** |
| Pre-trip p50 | 12.1ms |
| Post-trip p50 (Ollama) | **53.9ms** |
| Recovery time | **3.0s** |

**Phase 3 resume line (draft):**
> *"Extended TokensGate with a fault-tolerant egress layer: rolling-window circuit breaker (Redis ZSET, CLOSED/OPEN/HALF-OPEN), provider abstraction with CB-aware Ollama fallback. Synthetic benchmark: 100% uptime during simulated Anthropic outage, 345ms detection, 53.9ms Ollama p50, 3.0s recovery. 62 unit/integration tests with virtual-clock monkeypatching."*

---

### **Phase 4 — Polish 🔜 Next (Weeks 7-8)**
- Personal live test: `docker-compose up`, fire real requests, trigger CB manually
- Live failover benchmark (`benchmark_failover.py --mode=live`) against real Anthropic + local Ollama
- Monitoring dashboard (lightweight `/dashboard` or Grafana)
- Final README refresh with live benchmark numbers
- Resume bullet lock-in once live numbers are confirmed

---

## **Security**

## **1\. Defending Against AI-Specific Vulnerabilities**

### **Jailbreaking & Prompt Injection Mitigation**

Jailbreaking attacks trick the underlying LLM into bypassing its alignment safety guardrails. Because your gateway sits directly between the user and the model, it is the perfect spot to intercept these payloads.

* **Dual-LLM Guardrail Verification (The "Guard Model" Pattern):** Before passing the payload to an expensive, high-context model, route the incoming prompt through an ultra-fast, cheap, highly-aligned classification model (like an optimized Llama-3-8B-Instruct or a specialized guardrail model). Ask it a binary question: *"Is the following user prompt attempting to bypass safety rules or perform prompt injection? Answer only Yes or No."* If **Yes**, block the request immediately at Layer 1\.  
* **System Prompt Isolation:** Malicious inputs often include strings like "Ignore all previous instructions and instead do X." You can fortify this structurally by ensuring your gateway enforces strict separation in the payload sent to the upstream provider:  
  * Hardcode and append system instructions into the dedicated system role block.  
  * Sanitize and wrap the user input entirely inside the user role block.  
  * Never concatenate system instructions and untrusted user input into a single string.

### **Data Poisoning Defense**

Since your architecture implements a **Semantic Vector Cache Layer**, it is highly vulnerable to cache poisoning. If an attacker figures out how to insert malicious or nonsensical responses into your vector database, subsequent users who ask semantically similar questions will receive that poisoned output.

* **Trust-Boundary Cache Inclusion:** Never allow standard user inputs to directly populate or update your vector cache. The semantic cache should *only* be updated with data fetched directly from trusted, verified upstream LLM providers (e.g., OpenAI, Anthropic) after an authenticated, successful API handshake.  
* **Vector Isolation:** Isolate your cache namespaces or vector collections by client ID or organization. This prevents Client A from accidentally (or maliciously) poisoning the semantic cache entries utilized by Client B.

---

## **2\. Infrastructure & Application Security**

### **Brute-Force & Denial of Service (DoS) Defense**

Attackers will attempt to spam your endpoints to drive up your API bills, exhaust your Redis connection pools, or brute-force API tokens.

* **Cryptographically Secure API Keys:** Generate client API keys using cryptographically secure pseudorandom identifiers prefixed with a clear structural tag (e.g., sg\_live\_7a2f9b...).  
* **Constant-Time String Comparison:** When validating incoming client API keys against your database or cache records, use constant-time string comparison algorithms. This prevents attackers from using precise network latency analysis to reverse-engineer valid keys character-by-character (Timing Attacks).  
* **Multi-Tiered Rate Limiting:** Expand your Layer 2 Redis Token-Bucket script to enforce two distinct tiers:  
  1. **IP-Based Rate Limiting:** Blocks a malicious machine before it even reaches your authentication logic, preventing distributed brute-force attacks on your key verification infrastructure.  
  2. **Token-Based Rate Limiting:** Enforces the structural, granular TPM/RPM limits on authenticated keys as designed.

### **Transport & Storage Security**

* **Payload Encryption at Rest:** If you are caching sensitive user inquiries, remember that prompts frequently contain Personally Identifiable Information (PII) or corporate intellectual property. Encrypt the completion payloads stored inside your Redis and Vector databases using AES-256-GCM, utilizing a secure key-management system outside of your code repository.  
* **Secure Upstream Handshakes:** Ensure that all outgoing egress connections from Layer 3 to upstream providers strictly enforce TLS 1.3 verification to prevent mid-flight corporate espionage or Man-in-the-Middle (MitM) traffic sniffing.

---

## **📋 Security Architecture Matrix for Your Resume**

When documenting this project on GitHub or describing it to a technical interviewer, summarize your security implementations using a clear matrix:

| Attack Vector | Threat Target | Gateway Mitigation Mechanism |
| :---- | :---- | :---- |
| **Prompt Injection** | Upstream LLM Alignment | System Prompt Isolation & Binary Pre-Classification Guard Models |
| **Cache Poisoning** | Vector DB Integrity | Provider-Only Cache Population & Client Namespace Isolation |
| **Brute Force / DoS** | Gateway Infrastructure / API Wallet | IP-Tiered Rate Limiting & Constant-Time String Verification |
| **Data Scraping / Theft** | Telemetry & Cache Storage | AES-256-GCM Encryption at rest & TLS 1.3 Egress Enforcement |

[image1]: <data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAc4AAAHeCAYAAAASMOsrAABz4klEQVR4Xuy9d78VtRf2/byH+/n7+YnSOSDSEem9V5EqHURQ6VJFROkgTbDQbSAi0ntH75c1D1eOa86aNcnsnX065/rj+9nJmkySmcnkmmRmZ/0//+f//L8JIYQQQsrj//n//vdGQgghhJDyoHASQgghEVA4CSGEkAgonIQQQkgEFE5CCCEkAgonIYQQEgGFkxBCCImAwkkIIYREQOEkhBBCIqBwEkIIIRFQOAkhhJAIKJyEEEJIBBROQgghJAIKJyGEEBIBhbMEw0eMSE6dOZVit9cVI0ePztkIIfHs2PlVzlaf/O+NVg3SR5CmA4WzBJOnTI26GeZ++GHyz//9x7Hzm6+d7dh3x1ObTQ86dqpK7ty7m7PXJ1KfF/+8SAYNHpLb3lw5fPSIO65nL54lGzdvymy7cvWvdNtbrduk9q3btjn785fPk3btOzjbhV9+Ts+RMGz4iFx5IULX2jJuwoTCtEXbYtLE8vT506Sqc5ecvT6Q8ztu/PjctkpAXv0HDszZG4L6uBak6UHhLEGscO4/eCANb9y0Kdm0ZXMar++b6vTZMzlbCF2Xs+fPJZMmT85sf6PVm7l9KkELlKZN27Y52+ixY3M2odz6QDjx8ILw4CFDXonhCxdevHSJGxlIOjn+5StWJNt3fJnad+/dk8mvkmv28Mmj5J1u3XN2DWYYnjx7mrTv2DFYxplzZ5IPZszI2fVxANm/1Ztv5dKGCJUp+EZtofxtfTRvvtW6LNuPp34KCqevXNTf14aKKKqnj9j0oNR5Ja8HFM4SxAin7wbX+G6q+w/vO/6+fi1jx+jowaOH7hcdrM7j7oN7yc+//pK8+Pdlxq7pP2BAriyNrgs6SQgIwhCop8+fJb/+/lsmzYqVK138z7+uJAe/PZQMHzkyl8/R48eS6R98kCnj1JnT7rfL212drUPHTi6O+ut9bf0hgLJtxMhRzvZe/+JjAlo4JV/8nrtwPpPup9PV13TSlClupGnzsfvHgFG8hDtVdU5e/ps9zjZt22XSh8qw9uMnvnO2x08f584dyrx85c/k+s0bqR3XA2Vj+28Xf8+k19i28umqVd663L53J1PuN7t3ufitO7dTe9d3uiUX/7j0qt1ecenv3r/rrrXkgfrcuHUzd2w+4URbRLpSbeX+owfOjpkd3Es2b9lH1xP069/fHcMvv/3q7IcOH86kv37rhmsbuIY2vxC+ssnrB4WzBDHC+f706TmbpuimQseh4xAuCV+99ncyfsLEXB42v9gR59Bhw5Kx48a7sDxdywgN7NqzO/l808Y0vdghNqWEc/3nG1J7t+49UjH5bPWqZNv27Zm6CEUjzk8/+yxn86GFEx0pOkWE7bna+sW2NIwpdWzfsXNnLj+7Xylat2mb9O3XL5iHLz+fDSxcvCgTf/zsSRqe43k4sGGNtdt40bbfL11Mpkyd6sKDhw5NHxB1OhE9CKe0Idluf8EXX27PjGp9wol83u76jgvrtih5hUactv4QVrR1hFHGtRvXXRjCKe1Y74fj0w+lMdiyyesJhbMEMcLZp2/fnE1TdFNZ4URaPLGDh48fplOIRZ1krHDu3bfP/eqRsi4XowXpZGxZpYTz0ZPHaT52pIJOCSOPVatXZ/IsEs5ykXecYP+BmmlzGZUIekpd+OGnHzOjQ2CPuxQYTVmbvGuFWIRGc9aGUb21rV2/Lmez++vw1Gnvp+fClmHjwqIlS5Ijx46WlfbbIzUjNIB7BcJ583b1OZD97C+o6tIl8yDgE06k97VF2VaucIbiEE6fHeBhFXHfdSjClkVeTyicJYgRTiAjQx9FN5UVzvkLF+TS2DxsfrHCKeEz58567aH0wCecmJYV4Tz/84VcHhpMw534/qR7xye2uhJOPVUryIdagkx/z5g1K2O3x2njReABJJQeohDa5rP7bJhWtDabtpywL15k99kA3o3reO8+fcsWzn7v9U8uX7mcxkPCqeN2W30Kp4CHu9ADiw9fHuT1g8JZgljhxGgKT8eXLl9yNxG+mJVte/fvc9NP+GJRPpo5cOigA2nxO3vuXGfHiO3shXNuH2xr2669s+sb096k3bp3d0/nEEI9VepD74spzX0H9rtwx6oq914VH8wgTZ++7zo7RA7vVjFqQocnwinvPjd8/rlLo99x4lgxvYZjkanRocOHu/SYFsU7OfvRD0Z8OGb9lfGYV4KKfcr5+jcknAB5YDuukYyWOnd529nl3Zi8j9P72HxCFKWtPubsBzewaXr26u3s+OpXtxtB3mHiXRzSo+62XB3GiA7Hg3Np64b3pLatoM2OGTcuVy6m8bE/pkvxK3+dwuuEazeuudkQyb+UcKLtyLtR/fENprdh+3rXN+kHUWiLsKGt4FfaIpg2fbqzIS+ZJUC70feSTO22a9/e2aSecu+FhFOOF+3ZvrcvheRBXm8onCWIFU6Ap+nQ6AlP5biRrd0HPiIZOGhQzl7EgIGDyvqIpgiI2egxY3J2POFDnBHW74a69+gZnKaeOCn7ta4wYdIk7z7oeO3IA+jyKgUd4pRp09wHSnZbj569Sn7cVQTe+1rRrQSIof4YzIJrg/fS1h6i77vZ960a21ZKdfq4lvZLU5yzIUOr3x+WQvKfMNE/K4P7AufR2kP5t+/Q0d2ftk4hQvmEQJvD/7itvYhS55C8HlA4S4DRDkZggt3eUqkLISMti9dVVCDc7CNaFhROUhEYOVsbIUXs3pP9jywhzRUKJyGEEBIBhZMQQgiJgMJJSAXYv2IQQloOFE5CKuB1/dCFEFIaCichFUDhJKTlQuEkpAIonIS0XCichFQAhZOQlguFk5AKoHAS0nKhcBJSARROQlouFE5CKoDCSUjLhcJJSAVQOAlpuVA4CakACichLRcKJyEVQOEkpOVC4SSkAiichLRcKJyEVACFk5CWC4WTkAqYMXNmzkYIaRlQOAkhhJAIKJyEEEJIBBROQgghJAIKJyGEEBIBhZMQQgiJgMJJSAT4G4rFpiGEvN5QOAmJoGNVVUY07z24n0tDCHm9oXASEsnzly9S4azq3CW3nRDyekPhJCSS/gMGONF88c+L3DZCyOsPhZOQCoBwDhw0KGcnhLz+UDgJqYD/vdEqZyOEtAwonIQQQkgEFE5CCCEkAgonIYQQEgGFkxBCCImAwkkIIYREQOEkhBBCIqBwEkIIIRFQOAkhhJAIKJyEEEJIBBROQgghJAIKJyGEEBIBhZMQQgiJoCLhfPnvP8nPv/7iePz0SRrWNJb9zv27OVup9Bf/uJSz//Hn5ZxN8vGlv3bjWnL12t85e4hQepT78MmjnB34ykX623dv5+zAd8yx6YvsoXrWVfqmZmfbqsF3zLHpi+yheobSN3d7c21bw4aPyOlDS6Ai4Xz+8nnORgghpGVB4YyAwkkIIYTCGQGFkxBCCIUzAgonIYQQCmcEFE5CCCEUzggonIQQQiichBBCCCkJhZMQQgiJoCLh5FQtIYS0DCZMnJh8/+MPOXtLhsJJCCEkCIUzD4WzifLP//0nZxPQkPX2UaNHJ0+fP0vjXd7umm7Hr0bnD1788yIZNHhIrgwfrd58K7l153bSrXuP3LZyKarPW63bZOL4XbFyZW5/Gx89Zkwm3vfdft70hw4fTssdN2GCsy1bvjxTn9179zj70o+WufijJ4+T5StWZMr0gTr4jm3j5k3J1WtX03S79uxOPv3sMxdGHSTtr7//lqbx5QO2bttWU8891fW88MvPufTywYa1Sz44p2JbtGRJyXqG8OXfpm3bTFloK7q/kLQ379zK2Ww9dVjHQ9eM1A8UzjwUziaK7TQ06HTQodv0nao6u/DjZ0+SgYMHF+Yj9v+90cqF23fomEuj+e3i72lHVVvhtDaxP3z8MJeuSDhR95u3byZ/X7+W2a7T6PCVq1fcb+s2NZ07OuG9+/dlygAQTogTzgvW57x0+VIujY/tO3Zk4hAkXQcRJFwr2PEwAvupM6fTNKFzdPfBvTT85NnTzLmZ9v77yemzZ3L7gLHjxmfiWGtawiirT99303pWdeni7OUKp7WJcH6+aaOLa+E8c+5s8nbXd1x446ZNbj3aovwQP3fhfG47rpktl9QfFM48FM4miu1ENC/+ffmqs+ubs2OfVatXJ8dPfFcyH23fsfOrskZVsp8VTowUQ+VYQulg/2DGjFy6IuHEgtYdq6oyNoS79+iZdOjYKZN+9do1uTJBKeHU+do0PnzCufKTT5IfT/3k4iJI12/dCD6shMoquu/KFU48NOhtb7R60z1oST2l7NoI59PnT92DxshRozLC6UtflB/iaJto03o7hbNhoXDmoXA2UWwnIkBIVq2pFoElS5dmtqHjtPshrtH2ocOGuU4VYYzebFk+kNYKJ7ACF6KoPvi9cvWvTFxPK4b20WIlNttZh0aMdtpP7FY4r9247s6X3d/iE86tX2xzo7w332rt8oQg6bJO/vC9Y9bs2S6u6zN85Mg03c5vvnY2jDZ79e6dKadc4Zwxa1ZuO/KUeg4eMsRdA6mnTWv3s+dOT9XiFw8xuBYyswE7HuzkmG1+vrj9DV0zUj9QOPNQOJsooQ4Bo00ROd91sPvZuLbv3bfP/cp0YTkgvU84y6WoPvjF6Keqc5c0bgVZ7J27vJ3cvX/Xhdu0bZeO3mQ73hnKQwHi+w8eyJUJyh1xPn/5wpVj01lCwtn1nW7Jg0cP3XvKT1etypyHwUOHOj5bvcrFQ+dIGD5ihEszYOCg1FaucPYfMCC3HXlJPRHHNZB62rR2P2vTwon8cF1w7nR6iDOO1+4fik+ZNi0T54izYaFw5qFwNlFsJ6Lt8IcHfGnWrl+XS2/TWDvePdntIbBffQonphLxwZLEQ8J57LvjmXNx4NDBXP4IS3zSlCmZfLp17+5+yxXOUL0tIeFE+PrNG27UCEFCR6SnpoF85OQry06xYnSKD4MkXq5wAoiW3ga/irqeKEvqafPS+OppPw7CdbHCGdq/KI73zBKncDYsFM48FM4miu1EADrH879cSON//X01/TpUqEQ4EZaPQkJgVAqQtmev3u7dWCi/IkLptB0fhEg8JJw2H58dH6joOL4Ixm/Mx0H4QhkfIOmvXosoEk6ZroQgyahaRvsnvj+Z7mOPTbhx62aa/vdLF5MFCxem22KE034chGlfXU+x14VwIizCefbCOXc+Ed7w+efuHXVRfjqOD8f0NdPpSP1C4cxD4SR1wpChpd//NQXwwUr/gQNz9sYCH3mNHjs2Zw/Ro2evOqk/rhemTK29vsFXtZMmT87ZSdOFwpmHwkkIISQIhTMPhZMQQkgQCmceCichhJAgFM48FQknIYQQ0lKhcBJCCCERVCScnKolhBAiDgVaGhROQgghXkotdkLhjKAxhHPuhx+mf6bGn6zt9hi+O3nC5QXatmuf2hE/cuxoLn0Mki/+7F1qUYFS6Hqe/7lm4QPrVgxIOptHLFgWTvICPXr2zKUpB9l/3Pjsn++bMnphAAHHUNv21hDA20hdXP/GQBZIEOrzQxQswIAlBRFe9tFH7pzhun/19c5c2obm2yOHvWsJNwSh44dzBCzzae0ChTOChhZO+FeUTmHo8OG17iAq3R+r9NgVcywQePxOnjK14nIEvX85i7CLF4naAOG0tkqBR5C6EE6siDNh0qScvS45fPRIzgb+/OtKZuk9Czo7awN37t0t2VZINWjn4ydMTOP1KZyPnz5OXZtBOMUOn57WVV99g9WadLyhhROrT435b/GNkHAC1Gv/Af9azxTOCBpaOC/+Ue2iSOJ6JIfFvlEfrK0pNngPwYoshw5/69Y9lZVZsFIKOmDcqPjVnTE8NcAuHioETFXAWwSWB7v/8H6ubhYRToD9IBxYpBr5Y01YLNB978F95ylD0qFjhsh07FSV2mw9ZUFv8SrhE+WQcGJJOZyjNeuyy/H5CAmnXhIOiANkgJsKT+1yEwo+4bQeMbRrrc1btrjRh84bMwAyerUeNRYvXeKWYtPihTCOFecXHQP8iOryQvjOJ0Ana7ctXLzIdcBnzp1xS8eJXdoK0su5wIgddcaydtt3fOk8m2DBd2x7p1t31yawlJ5u3xjhYl3bn06fyrQTPDSiXCy1OGJkTXpfm8DISl8zLCEo5zVUbgh9zuE0fcfOmk4W5xjXzC41GAPaj667Fk60aVxP3Y6mTJ3q2g3ONc6Tzmvd+vUuvW8ZRb3gPNDCCXQd0BafvXiWXL7yZyaNPLjDQYK2o8/BPWCvmQ8siynXS7dpEc6jx49V91v/rV2MvLGeMO5f3FPa/yyWYJR7QB6u4VFHL72pHwrhAvCX33513n50XwXh/HrXN65OS5Yty9XZ3gMChTOChhbO0EXDE71s+3D+fOcHEGE0IjRiNCSsqypppn/wQeqmCr92HdQ1a9emLrt02bjh4N8xVA+NboxIL34hATrNeQsWuA5MRiO4kWfMnJnroG09MYLV5fjq4hNOpBN3WLhh7HYLhHPgoEEpOh8J40FEblJ08h//58sTafQoyyectt5Ys1XCeOpHvug0+vXv72zoGLB2LTpLWS8Xdlyrq9euujCO7yO1finOpzhADq3fqoGQwTm4tctasLrOEBqMJhG2sx/SViAsdgSLDhXnCsKDhz1Z01U6WZsP2i3qhcXNtR3nR86Rzt/mYeOyr4R1ue07+v2C6n1lkXlMc8p7L6zhO/O/EdLBQ4dy+5ULXkPgAQQeWRAX4UT7EVF5+vyZO98Io2OXhyWc69t3q9cgxkPSl19VCzjuM3tc8KbTu0+NH1stnLovAWiL+MUsk7RFIGmwr35YkL7HXjMfKAvtGMer2zSOSa4THrh0ffAgJA+B3+zeldolDe4BCWPdYu2T1zqIx/XD+RHvQmJv1769O2e2HQE8sFkboHBGUFvhxJM6Lo7GptGEti9YtCjZtv2LXDo0QC2Kdn8bF6xwYooY7yolXs7oBXmfPX/O/eKJ3m7zpZcwRp7o9H3bLL5tPuGUTh5AxPHEadNoIJynzpxKETtG73JO7agUrqognujk9ILiscKJkRAePD757NNk/ecbUrtvqtbmo+P6HJYD2pHv3TY6a/xu2rI5XfAcAqGPScq1bcXWD+8gdRzXCiNmiWOEI2G0Gz2DovOcPXduzq6367hcM1xz/Z7KlltqJgLppSPWZWCkiAeCcl4jFCH3leQtwqnLgl9PGf3ZEZGks8dvj8u+w4b44V7FAv7YV9yXAbRFnDuIpm6LSGc91Yi9b79+GVupfs43VSsPoZKnhCGcdn/MqmHEL3EINtIVCad+4NL56fTIRz80A1xnHRconBHUVjhjwUhJvwPp0/dd97vik09yjRq/9l2BbXA2LljhBDKNBMp5qtYjTostFx2Ovpkxlac9Xtj0RXkBn3BiVGBtRVhR1KBM+KTUadAWRCwxytPeWkoJJ560RThPnTmdXssNGzc6JF19C6dvBCeeYHwu3HD8mMaDTU916rZip+tsu4DnlvkLF2RsFoym7HECzK747CEbHgB0Z1+qXB/IB9O7MurTYLbk7oN7OXu56AdSlOMTzk5VndNZgXKFU4NzZm12qlbQbRHotghwD1y6/Id3NiN0zXz4hDPUb0EQ7UgW7uEg/BKHs3aMqCGc+LBQ7Hp6GudO2qi86wX6HSfEeNDgIZmyQsdE4YygoYUTT3+4cOjg3u33XnoRtQsj/QFRUQP0xQWfcOJpHe8XbNoQtoPU+MqFDR4vcGwI66lOX/qibRMnTU6/AJWRJdLJO7Xpxv+jjyLhhDBCDLUnFKRHuQijLC2cGKnJezZ8CSxp5J0z8hLhhH9NpEcYDxO6s8I0nvgMFQHFVKg8JWN6dNee3Wn6WOEE9nxu2749M0rEdkxlIYxO2Ofho6it2HYBIdBlytSytAM9rSpp7JSbLcNn0y7afOmwvRzPNrgevnzkHTVmCfQ27bqtFFo48UAhwomRN77qlPCc/85hSDgh3niXizDETR+Xry4h4dRtEa93pC2i7ck1gGDgWwWEca10+/OV5QOvbvA7cPBg91vUb/mEU6fBdZAwfM1KGG3S1gcPfTafIuG0ruI0FM4IGlo4ATpnXDxMOYlPP4CPJGDHy27pbIoaoC8uNg3eqfnsdj+L7SDB/oM1IxGbB4QSo0I0ZrmBBJtWbL562u146kQcIyfkDxu+ELX5WezfUXT++uYUkD+uCex492L9g+KDKmwTP6IQccQhjpg61lO1eE+EzmT2nDm5p3xcX+ynOw98RAHb/UcPUps9PzqPItBRaGfX2FfePQGI6L4D+9OHOMH6thSu36r+aAXTwNqOaW1Jj48/cC/Brj9wwoOUpNcfXMl7b4APOXzlAv3BFcKYmZF4Ubml0KMYgE4Zo1nkYx+4KhVOoD8OkulO/RATEs7q9GddXH8h6/zYqr9zCSHhBGiLyGf5xx9n2qJcA8xQ6NceeAj0XbMi5Njw3hh9V6jfgh9ZfX11HjKFi3tAf1woeWNUrH3J6nzkbzmgSDiRtlfvPplyBQpnBI0hnI2B7QxAOV8hkuaJ6yjVOyYftuOS92K2raCzYltpGkDca/se9nUADz76FQIcl9sZNgvau359ZKFwRtBShBOfdOPJdeWrJ3aMNmynSVoeeM8GUVyydGk6uoFdtxX8RUI+LCKkqYDXJRgp41sI/MWvLvozCmcELUU4BUy9lPMeiLQMMEX3wYwZ3lWV0FbkXSghTRF84IW/RFl7JVA4CSGEEFISCichhBASQUXC2dKmagkhhOThVG0ELU04sXqI7w/UzQX85QX/S7T2ugZf7em/cBSxY+dXOVtTI7TMGCGkGgpnBA0tnPq/R4JNo8FKQ1jo2NorBf9BLFVmXRNzvKXwuSGrazpWVSWXr1zO2UOgPv0HDkzjdXXNNm/dkny2unp5vNqCP9/7/pdLCKmGwhlBQwunoNdlLKKuOuHGxK5zGwMWIahvobT4fPahDuX6siy6Zr4l90LUpXCChj6PhDQnKJwRNCXh9LkV050wOm7tFklcKlm3Q0hj3ZCJHSuZ2A5U3AFZV1fwUoB1LLFupHiRKOVWzEdIOJEPpo6xeLuuJ8Ai8eL+TP4SIfXz1R9/CscScdYXH5ayw9Ji5U5Pjxw9OjetKWXimBGWFWqwlJmvPvqa7dm3NxW/WLdiWjjx527tSxOrwDx88iizoDVWRsJShFhj1LqoAvBggSXYrJ0QQuGMorbCCTFDx66xaXxY4cRUn3WNg1/phNFB6kWQsRi5XX6qVFiwnhV0Wu0fFKtx6G1t29Ucmy/fECIWIOTRQIfxh3txYYbrY9812rIRF6GCSMv6rnpBaKy/ibVD9X4+II6yFq0tIzTitPWRawa7bQ++ESeWGBN3aQBL8uFXhBP5aG8VqIde1FrKx/JtskA5lhWz9dJpCSFZKJwR1FY4S7nbCWGFE2uj6nUrUS/4k0MnjJGXzRdCCtvte3ccensoLPiEE6NdLAItcYzgMKKR/LHe5dx58wrzDREacYbqifLgesnafWltHB8OaZ+aUn88lIggFYFR65hx43J25BUjnLhm7dp3yKX1CafdX+IQTuSj358CrDEqx6WvPdqPnq2w+YZshBAKZxS1Fc5KscIZcismoxeM1LQXiyJXTiFBEnzC6UsXWgw5lD5ErHCKGyzgc39my9ZxK5x231JgmTntF1VAXjHCKdfMpo0VThlx6u3aLZ0Gwqmnqu1+cCjtc3JNCKFwRtFUhDPkVky/L4MNDl8R1q6c4HZIPFhIOl9YsMKJDh5eLGw67foJ7yFRZlG+IWKFE1y5GvZ+YtPquBZOOK8Wrw9ffLndeYq3eVnwdxebP4BjZ5nqtcJl08s1W7dhQ863Y4xbMRFOlGc/WIK/TAmLS6dSwnn77u2yvV0Q0tKgcEbQWMIZwrqyKgVEU/u9rGswhYuRirXXJ+jw8RESwIgTom3TlAvODVxPWXsRWLcVrpWsHaI2ecrUWnungJjj2Oy7W3xsFXMtseZwaBRswcdHy5Yvz9kJIdVQOCNoasLZ0oHvPLzv1TY7cmoI4FdRfwzV3GE7J6QYCmcE7FCaHhDK3Xv3pO7PZs+dm0tDCCF1CYUzAgpn0wR/t6D7M0JIQ0HhJIQQQkhJKJyEEEJIBBUJJ6dqCSGEcKo2AgonIYQQCmcEDS2c+A+g/Cm/PujT991k5qxZZbuQat0m+z9A/LewPutXG1BXjd1uwXmwtnLp+k633MLzgs0XX/7ibzQ2XV2B8mQJwqYM1k5ujL8OEVIXUDgjaGjhxCowWA/V2uuacjswrIaj/zeJ/WojnOWWWwmxecem12B5wx9++jFnB7XJV1NqYQcs5C+rPEE466rc2nLhl59zNkKaOxTOCJqScPrcigF0mvCMcvnKn8nAwYNT+6jRo5Nbd247d1U2r3I7WYyAdVod9rkVE7C0HbyPdHm7q4tjXVtxsWVdZmGR8ot/XHIjEvHygdV5kAbL/XXr3t0tG4dRnq2fxndMWAYQ7r2uXrvq/u/56MnjZOjw4Wn6jZs2uTI+MqvmYAk+iNL2HTsydsThVswKJ8I4/7KOLmwht2JwAYalESGMOG69Da7BUC72KbX83eNnT9x5snYQ61YMD0M2vdS9V+/er477y3TpPuBrW9OmTw9eY4R9LuvQprE+r23TUk+kX/bRR5lthDQGFM4Imopw6jVS4TsS3kgQhlsq2PELV1u6Y8LqNviFD8dDh2v8OALbgRUhadHxovMT+7MXz9yvFguANWylsxM7BFjS4VcvJwcbfHai80bYrnmL9VXRUaOTtXXTIO3AQYNSYIPYSh3wi7iM0hCXtX3hqky8njx49DCZ959/Tj3aPnfhfHLi+5PpviKcEydNTqa9/74Lw8OKPbc2jushdcAatwcOHUy3yQLyEA2sUav3s9h8NbLeLaaIJR3WqkW5aCvIH2vT2rx0eoB0P50+5ZbuwzUQu69tyTXGA5C9xoJeB1nadFXnLpk2Lel8bZqQxoLCGUFthTPWrVhIOBcsWpTxyiH5YCoV22x6gI5s0ZIlqbjqbTZeBNaDhcswLBSvR33v9nsvDaPOsuZrUd6+bVOnVYsOwLtXdNZF6UMgLRZuF2BDfW/erl5EXvKyv2Dw0KHpFKMt03dcOK8inJevXM6kt/vbOMQGrr8QxmwBRnoIY/H+ov0ssv3Tzz5zYTBy1KhkxMhR3nQQTj2iFDvSw7G5tQNcC4zKbdlFbatoqlYLZ6hNA13PazeupQ9ChDQWFM4IaiucsYSEM+RW7MuvdiSz58zJpUdnjylFhLVnFbt/uUjHrG0ht2I2XalteFcn4fenT8949vClD+FLW65w9nuvv5tytvZQ/nNeCbwIp532tPvbOIRzxn8fEHXsVJVeJ0mLOH4xCtf7WTBC0w8ymLrFKM96ZxFC3lGQHssX2vQAwmk/JCvVtsoVzlCbBrqe8BRUnx9XEVIOFM4ImopwhtyKYek53eHgvRN+8a5Tpr7O/3Ih17lJHM6wbVk+0OFt3JwdeYTciiHtyP+m9fD+EB5aJB2mJvGrp/Fkytel//el+/JX4rbeRfjSlhJO+dAJfihFIFAHcdWGushxYcQNV2CSRoRz0eLFqds1eE2x9bDxIuEscpdmGTd+fOpOTLcJEOtWTIf1u0yfcJbbtqq6dMnYgRbOUJsGFE7S1KBwRtAYwokORCPbMKWGON6jaddV+IgE4oNt+CBF7NKp4QMd27lh+k3y1+8UQ2A60LrLWrJ0aZoH/EjqbejsYPf5uJR9RGwwZYc4OlUZPYtN6D9gQC4fi04vx1tKODHNil/7DhijT9jlQcTa8cGM/jgIHx1VH1PN161yTQS8+4O9SDh1eu1DNQTcgSEtHlD0CPXo8WPOjg+05IOrIuGUd8E6va4L0NegqG19veubdB/xIGPzkrRo0yjTtmkKJ2lqUDgjaGjhJC0XfJSk4yK0hJDGh8IZAYWTNBRr169z7tLwRTLem+JLX5uGENI4UDgjoHCShgTvrGfNmeO+VrXbCCGNB4WTEEIIISWhcBJCCCERVCScp86cztkIIYS0LPr175+ztQQqEk6+42xYfP/9I4SQxobvOCNoaOG07rDwB337/8mmAurqW4+0XLdeFqzeg//46TyxrJ9eks8yYOCgzNJ/DQWuiXYfhuuEOD7uEZt1L9aQ6EUlymXSlCkZJwGNDY7h7oN7OXsMlbbFxgLrHvvuqXLB/2Ktw4VKqCv3hjiWGTNn5uzNEQpnBA0tnPbP5DYey59/lb8STSx37991y7yhjp989qmz4Q/9WMgAqx/h3G3ZtjW3nw9ZAF4/JGA1n/uPHrh1S/++fi23D9i8ZUvy2epVOXttwXkr6jhwfFj0XuKoO5atw69eCN7u11AsX7EiswJQKbCAAxZNwGIMWEzBbq9PQm0UC3vAA4+1x4D2iYUkcC1kTeCGInRcPmQhCVl5qpRnnBB6cY3aEFrBLBZ8Hd7Q7am+oHBG0NDCCfdLCxcvcmHtEUWIfRq1+5ebT6l1UoF2niwjRQin7rBD5VvuP7yfWcgbo099wyEfuBez+4WE0zdKxxJv1gZ85wLlhdLLdgnDFZjeJm2mnGP31bOcc68JjajuPbhflvDYdnbsu+Nl/R3Gd96K7MD3MFLOebIUlaHR1wZtzLeOb7l5FaXzXceY48LDpiw1CRG1D4qha2wR4fTVB/jOv49SwlluG6VwNn+ahXACueGwcoy+WGLXrp9CbsVwk8soTsI2H3Sq+ubGDQt3USiznI5TCyfEC2vZQjiRJ5Znwx/5sZC33c+H7WQw+tFTPFiCD4sDIAxBwOLgcrxaOBGX5drEDVnvPn3TDlOXg3yw3quEseYswnLe2nfo6O0shwwd5j2fFtjFcwrWe5Wl7ADWgJV6wl0ZfrHsnXgigf9L+BCVfGRd149fjSR1ebL2L0Y3WALRVwdr84Fl7/RyjQD/J5XlCnEuJS/8YhoaI2u5BtKRbv1im/sdN2FCui4tPqpAGMsUyrmFHYIdaqMAbswwAtM2n8u6IrRwwo2anSWwLutwvLgG1sUd7kXcL3JMsjg90ugZho5VVS5sjyskZLou1iag/eJXX2O0J3ELN3jIEOe9CGEIp+QFz0zwbIQw2g8cQiCMZTBLjb5DwolrJn5WtSs4OGrA6B7HidcVuH9hF+G0jtbtMoqyDQ/CyLNd+w7J5q1bkhu3qttfU4DCGUFthTPWrRiQNDptyPVTkVsxmweA/0k0WonDZZM4m/atO1qEFk7cRN+dPJEKJ0QUI5dVq1fn9rOgTna5OQiOuPMCU6ZNS87/fMGFdR0PfnsoJ5w2f4C80OHippQOGmIp29ERyc0u+YRGnLYMGw/Z4Vxawtp1mrD/YM3C7Hr/0C9Ax4TrP3zECOfM3OZp61AEziXSy5fk2j8msCPpNevWuV9Mhb7TrWY2AC7TIJaSDmG9Hq8doYfq6BPOUNoQSI/zAsGz97IvL23TLu7mL1zgREG2i59WnX7lq4fEDRs3evMqRVFavHu21zg0ioNw4uEKYe2yzt6HReWBkHDavkbywZrOeIiydhFOW16RcGofuHa/xoTCGYG92WJBJ42nV41NY8ETL25C/VSIho9GBHESYEfjxg1l8xBsw8Oi4NqFFN4fzpo924UhnBBSm0cILZxY2BtTRJVO1dp0WH5u6UfL0viqNWvcezubFp13KeGECMMZMz4kwna5Blo44Yja+qr0CSe8eNy+dydjswKj89Bx6dCATzjxzti3f+gXI1iEMRLCu2AZufryiAH7yGL1ur1Jm5M8fcKJbXjIw2hB0kE49fu+bdu358qzdQBWODEKif3oCecED2a+EZ+vXG1Dx37l6l8uXI5wYjR7+uwZb16lCKXFNd61Z3fuGofShxwI4Dz6rmWIkHDqh3cg+dv6SFyEE+/Q9fYi4fxo+fKcvSlA4YygtsJZCbhBIT76q0w8zekvDMUPI7yJYGQn9lLOkDGlptdARaOWTqU2wolyMI1TV8KJvK27Mfmrik6LqbVSwqltCJcjnBgBw7m1zQvny05jyxSYLkP/CqWEc/XaNYX52F88AMlUOB4srHBi9CPTiEXguHWHD5GD2GHaXj+UaXHEb0g4Jb2E60o4bdqiB0bBjm5Deflse/fvS6eFi4RT7h/MWMj3CTavUmCqXNob7lERGv2Qq68xpvExRWvzCQknZmx0OtuGLSHhhLtA/RAix4gH0+kffJCzi3DiXGqXeWfOnXXeemx6CKduKzHnsL6hcEbQGMIJ7BMa8Ll+AiG3YgDv8GDXgihTsniCxc0FG6ZaYBMOHz2SK9+CdBBh3TnJVC3AMWhfnEXA/ZS9SeR9HrCjP3xxizrjfY0Ip66/zkvezwF0OOUIJxCH0uL+DB2+vIO0XLr8h0sLgZepb9/xiN1Xz+p8qt2WQbTEJmnsL8B7LpSJEaIWTkydx7Td9/oPSOszYWLNBzR4KBD79BkznE3K9wkn3hNjO6alJV0p4cS7T6SVd2RShmbrtup3p6DIZZ3FJ5ylXNbhGmgXd6BIOEe/uv/wi/fSOh85LuB7/2zBwxTSwsWatsPmu8bbd9RcG7GFhBNArJAW92U5wqnPkS5DXj9ZV3C4rrDrB179cRDaiM4HD9iIz3vVVsUO4cTsGto1+iffTEFjQeGMIKbzIbVDRF7eQcrNhP8W6mnbxqI5eSsRB9ekftFCQGqPCKe1NwUonBFQOBsWPZLW/PX3VXZSpMnBNlm3UDibHhROQgghFUHhjEDe6xBCCGm5yH96WxoVCSchhBDSUqlIODlVSwghhFO1EVA4CSGEUDgjoHASQgihcEZA4SSEEELhjIDCSQghhMIZAYWTEEIIhTMCu14jIYSQlgeFkxCSA52DtRFCWjYUTkIKoHASQiwUTkIKoHASQiwUTkIKoHASQiwUTkIKoHASQiwUTkIKoHASQiwUTkIIISQCCichhBASAYWTkALOnj+XsxFCWjYUTkIK4DtOQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIATNmzszZCCEtGwonIYQQEgGFkxBCCImAwklIPfBGqzdzNkKaKq3efCtnI2EonITUMTfv3ErO/3IhY5s2fXrSu0/fXNpYnr14ltx9cC9nD1HVpUtU+lIMGDgoebffezm7pXuPnkm//v1zdh/2IaN1m7a5NDHgg65Bg4fk7KvXrkm+3vVN0vWdbmWlL8XMWbNyNh9Dhw9PJkycmLM3JXAO2rXvkLMTPxROQjxAHNDxazp07JRLZ8GT+4FDBzO2m7dvJkePH0sePnmUXL32d24fH3/+dSVnA2PGjk2GDhuWsxcRm76IzVu2JJ+tXpWza/Dg8ODRw+TiH5eSjZs35bZbfr90MRO3Dx2xbP1iW86G6/LN7l3uOl65+lfJ9OVQzhfXSPPX31eTS5f/SE58fzK3PYZQm4jFl0+nqs5lHQ+phsJJSAB0JBq73YdNN3vOnOT4ie/S+JlzZ5PJU6Ym8xcuSEaOGpXsO7A/uf/oQTJm3Di3fe36dcnJH753+eAXyL4I3757O9m7b19q27Vnd9KjZ6/k8dPHLv742ZNMeqDTa7vNH+zdvy95/vJ58lbrNhk7HgZQ13KE056DUuj0w4aPyGxb/vHH7oHjw/nzU9u3Rw67fd58q7UT3d8u/u7sm7ZsTs+dzmPCpEnJzm++dr+CbPOlBx/MmOEeeHC9tH3J0qXJ5St/OiH27afBgwOuscQx+pdw5y5vu/OMeolt1Zo1SZ++fZNDh79NXvzzIhn96iEJ9iPHjgbbBJB6yjUbNXp0sv/ggXQ7ril+i9qWq1/nLiWPiVRD4SQkADplEU2M9Ox2H7bjwUgTnbDEFyxalOzeu8cJ0NPnT9302P/eaJXuh2lL6ZTxa989oVP88dRPaRyjpx07dyYrP/00efnvP240MXbc+Mw+Oj3o1r2Ho1fv3pn6IiyjU22/9+B+sv7zDW7EDXsp4dy2/YvM9LA9BgtGmCJmv/7+W2qHqIhwYQSrrwHqce7CeRc+ffZMJj97DVasXJmcPX/O/QpF6We9etiBGCEMgYPgIDxx0uTkybOnLnztxvXcfpbQdlxj2YYHArQDhPFAgGuI9tCzV821kXbgaxOSBvXU5T168thNq4Pb9+6k5YbysfmRYiichASQTqbczgSjBXTw2obRyegxY9L4lGnTnFBAODF1KPaVn3yS2S9Upk84e/Xu48o4deaUG11ilKv3scKpy5D3Whi93bl3N92mR526Lge/PVRSOOWcYWpyxqxZJaco+77b75UQXUv31flIeNLkya+O77R3m8W3Defd2kLpRcgEvFfG7+Url19d43eD+1lC2/HwhIcLmw7CqUXd7m/jRddM0tt9fPmUu43UQOEkpAB0JAsXL8rZQ9iOByO1ZcuXp/E1a9cmK16JJITzI2WfMnVqYT5CXQnn3ft3k3Hja0amI0aOcmV+d/JEStt27d02XZc169YVCieOCwLgyng16rx157YbPdl0FpQBIcC0rLbp+mzfsSOzzeZRtC1GOG25QOz6Qya7nwUCjNGjtWMqFlP1Esc0Oz5YwnnDg0YofxsvumaS3u7jy6fcbaQGCichBWzYuDFnK8KOVoB0Rl3e7pqGITC6k8IUnW+fgYMHZ+x1IZzI277DFLt8cYp3bGJ//vJFMn5C9VehSFMknKgHRj4It+/Q0aXHe0GbzoJp2es3byTtO3ZMbTie/Qeq39V98eX2ZN6CGrEp6uB922KEEw83+oMleQ+5aPHi5PqtGy6Mc2r3s7zTrbtLI+Ip6du0bZuGMdqWcLnCqd/R6jT6muG9OUbHI1+1F/tVdaht4X2ynfYmfiichNQheOKHKGpbj549XWcFcXy76zvOhjSrVq92H/tg2/YdX2b2kfeP+NhHd7yardu2FQqnL73P3q17d2fH1DTe7cE2Xb2XBfhSFqNHiFeRcILde/akxyvl2TQWCLkvHd4Rw66/tLX1FzumVLVdvy8NCWcory+/2pGzgYOHDjmbXFObnwXvRSUfPDiJXUaLeFcq17eUcGKGoHqf6mltoF8nyDXDg4qe1r567WomH1/bQru15ZEwFE5C6hhMvcl0ZQgRTmsnpDGAaOKrWmsnfiichNQDbdq2y9k0FE7SlKjtohMtDQonIYQQEgGFkxBCCImAwkkIIYREQOEkhBBCIqBwEkIIIRFQOAkhhJAIKJyEEEJIBBROQgghJAIKJyGEEBJBRcIpayMSQghpuVjH4y2FioRTvB8QQghpuVA4I6BwEkIIoXBGQOEkhBBC4YyAwkkIIYTCGQGFkxBCCIUzAgonIYQQCmcE02fMyNkIIYS0LDpVdc7ZWgIVCSchhBDSUqlIODlVSwghhFO1EVA4CSGEUDgjoHDWHa3btM3ZhDffap20evOtTNo3Wr2ZxhGW/fGr0fsUleFj4ODByajRo3P2GELl2nr+741Wme0zZ81K2rTN198em40LOF++9KE6vdW6TaYOsh12mw/S4ZpYO9KLHb86/xA2D8kHZei4BfXSbcCXV6xdH3/HTlXJrDlzcuX6sNcOddNxewyxcWHipMmZ82qvsWyTuL5nSP1C4YyAwll3YL1HaxNe/vtP8uKfF2l89JgxyZNnT9M4wgMHDUrzuX3vTorO//qtGy6forKECZMmubTXblwvK32I+w/vu3ogDxyH2O/ev+uAHb/v9R/g7F3e7ups+w8ecL/bd3yZ5gNgkzDsj589SW7eueWODduk0175ySeZ/P++fs3ZIQg///pL8uvvv7ltW7Ztdfbbd28n/d7rn9ZPjvmHn37MlTtk6LDkyLGjycMnj3Ln+vDRI8nDxw+T+48euH1CIiDo45IyYB88ZMir++tFelyffPZpZj/Yfrv4e85m61Nkl/Mj50iuAY4N137fgf3peSji1p3babhd+/bJie9PpvG3u76Ty6MoPmPmzNz2Pn3fdbZTZ06530WLFzv7suXLM8f1xZfb0/xw3uS86rxI/UDhjIDCWXeEbnB0RH/+dcV1AroTPn32TLJ2/ToXPvbd8ZL5aHubtu2Stu3a59KEuPvgXjJu/Pg03vWdbsm9B9UdfClECADqb+tn42fOnU2WffRRLp9QeggnOmeJv/j3ZWF6CKdve0g4Q3GIy7wFCzI2AOGc++GHwf1CbNu+Pb2eAMJ55eoVbz7jJkxIvvp6Zy5vGy9lB9t37EjWf74hjXesqnIPBBLHg4zdx7Ju/fq0faAsLZzPXjzLzIhImus3b2TiOjxg4KDkx1M/ebdrIJzW5ku/cdOmXBpSt1A4I6Bw1h32Zhf2HzjgOsrZc+cmX+/6JrfPoiVLcjaMPgE6IF/+yz/+OFdOCEx32bpNmTo1ZwuhhRPY/Wy8c5e3nQ3HbPPypbfCefT4scL0EM7+Awa484NR54pXI1PYKxHOL7/akZ5rEZiGEM4bt266B6pvdu/KTKeGygrZgRVOtCfka9MV0bNXb1fGoMFDkq1fbMsIp5St2y5sDx49TK+bpMGUr/Qpus6h+kM45fzLjItN375Dx8w2Uj9QOCOgcNYdoc6hqAM5c+5MzoY4prSAfWoXnj5/lisnhHSI1l4uscIpyPRu/4EDC9NDOPWx2XysDcK5cfMmB87DqtWrq8urQDj1uZ79n4D5hNO+A/ThE059XH369s3kid/2HTsmj548ztiFvfv2ee32OKxwoh4bPv88k6YUECbMFEAMERfhHDtufHL8xHcurMtFGO8jZepetqEeK1audGFMU+MXo1W7r8QhnHL+gU3jO15SP1A4I6Bw1h2hG7yoE4AIWJuNW/uBQwfduyu73Qc65SXLluXsMVQqnADCYLfbuB5x2m0+W3OcqrV5SFsQtN3mW2QHVjjRAX7/4w+5dEVAODEzIeIlwnnnXs07VF898WD3wYwZabzc45J4qalaXE/2UQ0DhTMCNsq6w3YOwoSJE9MwpuXOXTifxisRTvDLb7/mtlvOXjgX/CoRU8ChciwinBg5Yp9p06dnttt8rlz9y32Qg/DI0aNz221cCydGJ1oEfOm1cE6aPDndPnXa++6jHoQPHf72lQicLsynlHBilIn3e/LBSimKhBPvlKX8qs5dknbtO6TpMAW6YeNGF7Z1FEJ2YIVT0uOrZoQxKsTUvN1PY6dCRTh1ubrtajvOucRtfyLHhbYoH0JhNPzHn5dduJRwginTpiVVXbrk0pC6hcIZgW3opHJws2vQKXzk6Rh0pxASTg3e8dj9AKbWbN5F+ez85ut0G/6mYvMLIV82QgTsO1eN7nwPfnvI2exoVfbTcfuOE9shWmvWrcvkLx+8yDkDP50+5T6Ukn3xhS3s+uEkVK5M1Wpgh3AijK9SJ02ZkssnRJFwgt8vXXQCZ9/hQkSlbFtHociukWuA8ydf3FpR9eETTrRd/a5TytO/AF9BSxxfQvvSAzmvV69dTW24R3T98c7a7ueLk7qHwhkBhZMQQgiFMwIKJyGEEApnBBROQgghFE5CCCGElITCSQghhERQkXDaT/YJIYS0PPr1r/kPdEuiIuHkO05CCCF8xxlBYwmndVtU1+B/X7JUWKWIayNrL4fxEya6P7pLXDx52HQxVFqXWPDfxXKWmCtFbY+3HLBkIVa3QVi7pyrn2tlrVB+UU49ykMUM6gt73mThDIlbF2v2mGxcgBcanY+978WFm12ow6YL5S9oF26+ckLAGQFW4cJ/bu225gruO73ARrlQOCNoLOEMdaqyzmVtwYow3bp3z9ljgPcQcQkF7yZ2exFwezV85Mg03rtP32RGLTu/0DmrK0aOGuXKwB/08Yul1GyaGDZt2ZyzhRg6bFhy6PDhnL0ILGSur4t27yVhu48Gqy/pa1TXYKEGrNqDtoA6ifuzSqjk2se0WesWTZwIII57AIspyAIUEDtdnxEjq9uNzRO+NyUs+cB9mU6LRRFgR96ww0GApNd52bgFq1pp92TlrKwF8KqqV+/eycU/LuW2NQd817hTVeeS58sHhTOCxhBO3HjwrehzPYWFu60N2CfSUvYiyt1HP+U/fvo4XcFHsE6INVY4iyj36biSmwGUO3qE/0ncdAjDZZld9ajc81YKX31Gjx2bXPjl55y9iND5wAo91gbsqKk2wlnONYNwis9VvbpOOdhzHbNvpfuEVrGSMAQVo3ScR4id2OEGzu5n99VhLLm3ecsWF4Zwil38lyIMl2WytOO8+fO9+WusIwEf9prBO42vLQLbVuoae33LwdYfhM4LHB/YVZ9KQeGMoDGEE66csP6k3CQA/ijRCDSyDWG4YcLv1m3bUhsW9cYvRob2Bkd81Zo1mXLhSNjt95/XDlsvixbOy1cuu2XqEMZSbfDK4VxaqREyfBoiX4wysE06ZT0S0vkv/WiZsyEt8rflW+z+PjvWDZXpRzjLxpM8FnoP7auBkIRuNuyPzgy/s2bPdjZZ0g1rxOIaiKcMHLfveNFZ4oFJpq2HDh+e5q3RnWkIiHrIdZZPOLFOKtbQlfrCpoUTi5Vj2lfSIy08hSA9RuJiRxxOt51jcuM31KKFs1v3Hq/aTHUYfLxiRSZPCeOaIX7tRvV5smmw9qt2Oi31xK+UtfxV3vac6nqFKCWccEiOWQSIyqXLf7j7Cb4/ce7sfsNHjHB18uWDmQzxP2uvtaTD+rsSLucYQsL57ZHDzmm2XDO4o4Md/V7oHCFs24rEMRKX9G3aVk8f45rh2sJmr9nlK3+6h25ZZhG2UL+F62bT44Odkz9879ZM1v1WUX+py7e2IiicEdRWOMUtVtEFtEgaCKd9irIjTpsfOhRtx3qm+MUT8DvdaqZm16xdmxFOjKBw8+i8SqGP6fNN1YtVY1oKC4jrNL4wGrkdzYiwCPDTibVWQ0+9FnsufHYtnACLlc+YOdPdfHARZfe1oC6yziw6RdgwyrDpBKSTDsRi6yujDN/22BEnxCPUWVrhXLBoUbJt+xdpXMqFcKJcxDH6kO14Wl+8dEkufSgsD0wa2EWIrPszEBJOe860HevA9u3XL2PX9cT5lfuhKK8QIeE8e/6cEwTpKyCceCBDBy/pffvZuHDtxvXUDuFE/iJMvXr3cXYIx5hx45yQiHs2nZ8FbcHnngzCqR9utYNveO6x+aCt6LguF/fR+V8u5Pbx1U0/JAE5d5LW9ls4p/KuXtKjb4Rw4jyLffeePZl8fWWXs80HhTOC2gonphxwgTU2jQbvE/RN9NXXOzPbSwmn9Q1oG6Cks8IJLxqxrpZkxImy5OMEdH6If3fyRArsHTp2yoxA8O6klHACGXVqv5sh7Lnw2bVw4iZDp4F3q0gTciztY8x/goKwFTxNqE6+bTYfvT1WOHfv3ZN8OH9+zg6scOJBZ/7CGi8o6IjgrQTCidcFtp64FnjCt9cY6LQSxpS97x7QI067r0848UEHytV10WngUcQ+ZNl6Llxc0/Hb4ypFSDjhRxSOrsUmwgkRl/fYej88EOrj09txH+lrAeFE/rgeOr2MuGTUautlCT1EQTj1twVahHzCqR+KbXoIpxWu0DVDffV1kTYkx2H7LXlPrNPjYR/Cqd9jwpGALceWXc42HxTOCGornLFghDrt/erpD2Avru6kAJ7U9U0FjxV6P9sAJZ0VTuATriJEOOERRM4TBPLug3tpGl03fSwoq5Rw+jrPIkJpYJcOFWERTp0e57GUcOp89P44r7iJxS5T1rYMi90G4fTlD9DxiUuwcpgwaVLmOmiscMK1mf74Q8qVqVp05PDQItvxGkE/ZOnRqK6zPT5LkXCiQ/fZdRjTndZuy9T1tEKAtDHv0kLCadOJcIbS+fYJbbdTtYL1IOPLU1NXwom2EmqjPuG0aeSa4dWAvn7SN0laX7+l8xFbpcLp84NbCgpnBA0tnPZi+uKYKkS98CSPTgs2vM/Ce05xpVXUAOHoGdsBwoMGV39qjqdJdM679uzOletDv+O8eftm+qSMJ388CeOdD95XSBp8FYr3FtiGBwARTtRB6oRfmfbFTY0bGW6fyqkP0kAABXlfg1E4RrsbN21ybqxEOOFGbM++vW46GG62SgknpqlQhnwFqkd0iOOzffnSGDbExa4da0N49PEC2CGcECjUE9P0PhdUqKuesioC6fXDkmCFE+DDJ7w3w/vezVurR776HSfOk7wGAEgHH5KYEtbu2/R1KnXN5KtatBek1SNqxNGmIf46H8xA4Fri2vnKwocyeoQj9dy7f59Lox9w4EcU5aMM7bYtRF0IJ75fWLch78ZM54N3eX/9Xe1arC6FE3XSwB4rnABl2baC9i0fQVkn8rhmmKVAe5J6QnwRxnXBVLR8zyHbff3W/oMHculLCSem0HV/KXbcZ/oBtxwonBE0tHCWAg0O/yPUHQDA01vRV6wx4DN5O+UVC+qCjwKsvdRUtQUjWOsYuhJwg8mn/Bq8J4o91tANhAeQcjrgEDJV2++9/sGRUDnvYYUePXu6jijUAVpKPThY4OezrtqcBVOWRfXBiNraQqCe1p+mgBmRhnQCXUrgmgtF18YHHlZ9o178DS3mv8Kx6YHtL6s/Nvwzl64Uofv+dee1EE7y+mLfcdYV6GysjZCWSqnFIkJQOCOgcBJCCKFwRjC9lqvDEEIIaf7I4ictjYqEkxBCCGmpVCScdCtGCCGEbsUi4DtOQgghfMcZAYWTEEIIhTOCxhBOrJ+K/3vhT76hdU7rC6w12VSmp/FfRvxRGedC3Dg1J1BvgNWc8Id9u50Q0nygcEbQ0MKJJauwQobEbfkhdz6hP/HH/uFaOntrDxEqt9ztReh6nP/5Qq2+cD599kzwT/Mxf+Jfu35dbr3gEPY8Yj1gHY85N0Vr1ZZaVCKmHEKIHwpnBFa46pui8nyunwDiWJoK+4r7LXGVpbH5WSBMW7/Y5oQbq21I3viF2yf8opOWJduwDUvY4Rd1gw3L7ok7LXE7JaNFWagZnlFkSbEQWBMz5MLrvf4DXD44Xr38HGxYPk2WxNN2jSzFB8EU92c6PeqPRdwR1ovL23x8/lI1Ok+ApdT0Nuu0WK9RrPe35epl2LDWK2YIYO/ydldnwzVAvHuPnmW7TCOEFEPhjKBIyMoBU61YT1Zj02hCnRyWq0KHbtNhOlN7HbHLq/nyC9UHQgdhxBJkEDex4RdrY+Krstlz53q9bthybNzaELbLBmqwzi3WqLV2mw/WIZ07b17Orj1MAN+IU/s7xfq8skau5AVPNXL8QuyIc+iwYW6ZPKwjLCM/rAsLO8Ljxo9P3UiFhBP4Rpw4P3jQQRgPNrLAP8CSYr4FtwkhlUHhjKC2whnrjzO0HQteL1m2LI2jXiKSV6/97fbDYsZ2Ws7mh1FWqD6+MBakxmLIiO/dt8/5rZQyxHGszcfmBbAPbNgHwB+fCJ4PLKge6vh13liEXJzjajsW5Nb7+IRT1wcPJdoPItbrtccAYoUT5wy/OG/abtPhN1Y4MZrEYt1yDDo9hPPdfu9l0hNCKofCGUFthTMWeBDQjpH79H3X/a745JPMCMx2vkB8YWqbjYcQcYQIixDDjoXR4QFBvFTo/OClIFSOjYdsIeDHT7ucat+hZiSt83l/+nTn39DayxVOHddcvXbVbdf+G0GscJYK67gWTswk6HQ+4cR7X3FsbIFwYqrW2gkhlUHhjKChhRNg6lXeE166XOMn0ef6SUZyeB+I6VTbKcNNUDluwrBdL34MDwTyzgzb0HHj3ebf12tcS8EOscZ7Rsl/ydKlGXdauoxFS5a46VG4+SpVHwAn3kiHd3r4lZHu7Dlz3Dn64acfM9OTOk8rnN26d3fb4QJLHkA6VlWl7s+wTR5S4Apt8JAhLiyjWUFG7DjXpb4+tsco50NcwcHZNH71xz3i/gyiaPdH3LoVgw1TzGgTMm2LawA7HmzsNSCEVAaFM4LGEE4A11IiXJqQOx9MWWrHsBr4fwy5qaoNEDI7iiuHnr1652whIOZ2ClOIdQcFgcKHRdoWcn9WBI67Lm6iIUOr33NqQu7PBJ9bMUwrWxshpG6pi3u+OdKshJMQQkjTgcIZAYWTEEIIhTOC2vzpnhBCyOsB3YoRQgghpCQVCWepLycJIYS8/tCtWAR8x0kIIYTvOCOgcBJCCKFwRkDhJIQQQuGMgMJJCCGEwhkBhZMQQgiFMwKsrQoXUGDegvlpWNNY9hmzZuZspdKPGj0mZ4fvSWuTfHzpJ0+Z4pZ5s/YQofQo98N583J24CsX6T+YMSNnB75jjk1fZA/Vs67SNzU721YNvmOOTV9kD9UzlL6525tr26JwEkJy2EXlCSGEwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIARROQoiFwklIATNmzszZCCEtGwonIYQQEgGFk5ACzp4/l7MRQlo2FE5CCuA7TkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAEUTkKIhcJJSAF0K0YIsVA4CSGEkAgonIQQQkgEFE5CCCEkAgonIXVMj569kg0bN+bspJid33ydszUncM3btW+fs9cnj548ztlI/UPhJMTDu/3eS/r175+hQ8dOuXSWVm++lRw4dDCNr1m7Nrn/8L77Ovfh44cuvPzjj3P7VQLqZG2WP/+6krOFQB1v37uTYrcX0bZd7QVj+44vc7YQOK63WrfJ2X280epNd2z7Dux3v5+tXpVLE8OpM6eTXr17Jxf/uJSxr1qzJmnTtm0ufV1jv/S2cVL/UDgJ8TB46FDXIWlsGh8QRmsD2P9/b7TK2UsR2ufFvy9dB65tEAibrtx6l5O2SKh8whmqe12AupYrUtduXEsWLFrkwqjTg0cPM9vffKt1bh/BHjNGlHV9XL7r5gMPZfi11+mHn35MVn7ySS49qT8onIQE0KJ58ofvc9t92E5N222H+/Lff5Jbd24nL/55kTx+Wj3lNn/hguTu/bsuPabh8Csj1GcvnrmRIGyHjx5J8zly7Gjy9Pmz5Nfff0tWrFzpbAMHD87UP1QvW0drE/s3u3elZYv9p9On3DHcvHMr+eSzTzPp/75+zdUHdRZ7u/YdnOA/fPLI/YodDxsyKtfl3ntwP/lw/nw3usS21m2qhdIe1/1HD3J11th87bbLV/50vxhFwvbtkcPJosWL3XHh+PoPGODsz18+z5Ut+Uj9R44aldquXP3L2XD9JD3EHvYfT/3k4jg/+O3YqSpTH7SHo8ePpXm58/b4YfLHn5dzxyMjantspP6gcBISYNbs2bkOsgiMTkJpYbfCabcXxcH5ny/ktqMjfvLsac4eihchxwr0dCbiw0eOdOEbt26m/23VeW/asjmTvn2Hji78+6WLyQczZuTSb/j882T33j258nUcwin1wDTrjp07M2nLHXHafIVly5d700E4MYoTO4RMwu07Vh+Xj1NnTmWEE+Bc6YcEAOEcN2FCWt7BQ4eSmbNmJWfPn0umTJuWppPtGC2fvXDOhas6d/Eej89G6g8KJyEFoENauLh6mq8cQh0Y7Fo4MXqCDSOqRUuW5PazcbH16t3HdcayfdXq1S783ckTKXYfm0+IUFpt37Z9e/LxihUuDKEQu0wj2vRTpk5NTp89k7OXE4dwdnm7qwtPe//95PiJ7zJpayucGNn70kE4Z7wSMrHLbACoRDh378k+IEA4cR2lvL379iWz58zJXUe5lr9d/D0ZNXp0ur/veHw2Un9QOAkp4PGzJzlbEaEODHYtnJiS1SJn97NxgFEc7BBLseGDpbsP7qXxru90y+xj3+cV4SvT2rVwYhpT7IuXLsmkl2PFdKM8eOh85i1YkJlutttBkXDiuPAeWqcPgenNFeodIKbG8bt67ZpMusYWTgjk8BEj0nTvdOvufjEylg/O8D7WnieMXmPbKakdFE5CCiiaXvWx/vMNmdGXYIUTYdg2b93iOvbbd287+5KlS9OvP/Gr88DHQBs3bUrmvRqlDhw0KLVjf3TG+CpV8hGmTZ/+3/YrroO19dKgTLx/FLRdwlo4USbyhTDsP3ggkx4dOeqq9+33Xv/k519/cYKp7RAFABt+Z8+d6+xFwonjQnq8e9UCHgJppVx9XjGNimNCHjJNWolwSv3xXlREDuUgf1tmSDilTezdv89N2z5/WS3wQOqPuuhzJ9vatG2XqxOpPyichNQx6MjKFdyJkybnbCEw0kTnDvDO68T3J9Nt+EBk9JgxuX0ARjH4b6m11wX4qMWKiXTsEEqbHl+l9u7TN2evBIzAJ0+ZWva5hvjiAyVrnzBpUs7WmOD84F2mtQ8aPCRnw7tnO3In9Q+Fk5B6oK5HABhh6r9GrFu/PjcF2FSwIyJSf8gXv6RhoXAS0kx4+vypEyWg/6pACGlYKJyEEEJIBBROQgghJAIKJyGEEBIBhZMQQgiJgMJJCCGEREDhJIQQQiKgcBJCCCERUDgJIYSQCCoSzqHDhqXMWzA/E29s+4xZM3O2UulHjR6Ts48ZOzZnk3x86SdPmeKWT7P2EKH0KPfDefNyduArF+nhtsnage+YY9MX2UP1rKv0Tc3OtlWD75hj0xfZQ/UMpW/u9ubatnwOzFsCFQknFkTGYs3g8dMnaVjTWPY79+/mbKXSX/zjUs6OhbGtTfLxpYeX+avX/s7ZQ4TSo1wssG3twFeuLBBu7cB3zLHpi+yhetZV+qZmZ9uqwXfMsemL7KF6htI3d3tzbVvDhtd4c2lJVCSc8IRubYQQQloWFM4IKJyEEEIonBFQOAkhhFA4I6BwEkIIoXBGQOEkhBBC4YyAwkkIIYTCSQghhJCSUDgJIYSQCCoSTk7VEkII4VRtBBROQgghFM4IKJyNxz//95+cTXPqzOlMfNv2LzLxo8ePpflodP7g7+vXkukffJDL38flK3+6ffbu25fbVi5Hjh3N1Gfrtm2Z7fa4Q/HxEya6pcBs/hd++Tl4zD586aWT+On0qdTWrXsPZ3urdZtgnjYf2FasXJnGf790MRk0eEhmn42bNiVt2rZN4xMmTUr6vtsvjc/58MPk+x9/KKxnCJte7G3atkuePn/mbJu3bMmlt/UM5QPuP7zvbDhXvrL//OtKrl6k+VGqrb2uUDibGbaD0ixcvCi3Xcc3bt7ktfvS9+nbN3n24lkybsKEXBoNRErEGfv26t0nl6YcIJzzFizI2QGOCx3t3FdiITZbf4mHhNOmKxeb/th3x5Nff//NhTt3eTvdXko4rQ3CufObr114+MiRuTSI796zJ41DOHUaEU6JT3v//eT02TO5cnzcuHUzZwPIf8TIUS6M9agnTJyY2vEr9WzfoWPGbrl7/24yY9YsF8baqcdPfOfC3x457M4Twnv27U1u37uT25c0LyicEVA4G49QZwUgdHjSb92mZqSCznTt+nW5fUP5aDu8IJz/5UIuTYhDh7913jEk3vWdbsm9B/dz6XwUCSeO641WbyaPnz1Jbbb+Eq9v4bTxM+fOut/aCCfYtGVzbh+9H4Tz4KFDyZKlS128roVzyNBhydVrV3N2oOuBemI0bO02fas338rZX/z7MmcjzRsKZwQUzsYj1FnJttlz5yZf7/omZ1+0ZEn65C+2gYMGOQYMHOTNH9O6yz/+OFeOBZ3klGnTnMBp+5SpUwvrqykSTslD52XzlXhDC+eCRYvcbynhlHPd5e2uzmaF8/qtGzV5LlyYbNi4MZMfhFPywm9thNN37bds25p8vGJFLq2klzDqif1sPmIDa9audduWm/zGjhufPHryOOk/cGCuDNI8oXBGQOFsPEKdMzolEUab5sy5Mzkb4qfOnHL8eOqnjF24duN6rhwfmLpDGXA3ZLeVi33HqbfJcUEQh4+ovlFtGonHCqecm1DZpeJ4YMBvKeGUcz17zhxn0+84wQ8//Zimx3tGPIxgdPfpqlXOJsL54fz5broY+dRGOO21R/kyW4B8kQbTtZLeV0+dD9BltGvf3r1vRxrMFogdD1NPnj119o5VVbm6keYFhTMCCmfjUdQ5Q7gAwn36vptu69ipKrefjVs7OmpM+9rtlnf7vZeGUWa5U7OW0Ihz4ODB6XHBF6DUD9N+b77VOk2Hzhi/scJZCpvexs+eP+d+SwmntekRJ949y5QvBNNeS9hFOMGhw4eTHTu/qlg4fVO16ADxPlLicFIsH5pJHXQ9tV3zvzdapVO5ANP1kg6jaJ3Wtz9pXlA4I6BwNh6hzkbbZ70ajZy7cD6NVyKcANNq48aPz6XRYFSCqTmEf7v4exoGmAYMlWMJCSe+5NRxyQ8fJMlHOu90656sWVf9Hre+hfPw0SNpnTDtKttrI5w6zbbt2zPCAztGb1o4xV6Xwil5yoj+6fOn6RfDuv4IV3XpkrPbfDCVjPDuvXuS/QcOuDD6jbe7vuPCeFd787a/HqT5QOGMgMLZeKBT0uB90UfLlycnvj+ZSyfhkHBqfF9KyujH1sFy6fIfLp1+hwowWixnfxASTru//lgJU5bY/vjp49QG4bTHVpRfKXzpcZyw46FBhECE01euz26Fs3uPnu4hBdv1hzUQ0X0H9ueEE+eqUuG09ZFrj7+/4AMs2ObOm5dJL2HUU+I2H13G9Zs3nM1+XIaZAtgxe2DrRZofFM4IKJyEEEIonBFQOAkhhFA4I6BwEkIIoXASQgghpCQUTkIIISSCioSTU7WEEEI4VRtBUxNO/LEa/3Wz9rqiX//+bsUWayevP/XdtghpzlA4I2gM4YRnDPz/6/nLFxl3SwD2ZcuX5/apK/BfNPs/tRjkf5QA/znE6io2TW2pTf3KAXUWl1ONcf0t9nhtvFyWLFuWfPX1zpxdqO+2RUhzhsIZQUN3nPBDKB3j0OHDK+4k65py6wHhlCXhOnTslK4BWpeUW5dKQf4YeSOMBb3xB37ZBu8r2mVZKfBHffuH/lhQn9Cf9GMoJZyEkDAUzggaWjgv/nEpGTmq2k8gkCW/wMkfvs906trWq3fvZPuOL1PREuBw+buTJzIrtGCfUFgWvRYbhELKwK9O70MLJ9B5ST6r165xq6qIP0QsI4d1QbE8mj52OBvG0nYYeeuRq80Txy7xvfv3uWsmy9LpchF+8c+LZPHSJek2HyFhknzkXMii5wD1x0PC1i9qnFLb9D169kq3YZFxW88QkgfC01/tp+u3aPHiXLlA1mPFcoTipUSEEx5lsNqNTu9rW6vWrHG+SuFCDedt9Nix6Ta5ZjjfOh9CXlconBHUVjgx1Yr3RhqbRhPqtAV4ZtDiAnbs3On1L6jz0mKh7b7yfKNEXzofeqrWt4/PJuuwAiz2jaXkbBpfndGZh9LI+qF6m3YOXQR8fEKssQ/Ord5WasT52epVbtk4iftGnFgsXUQX9Tz/c3apNgvqgZHv55s2umvjO4e23K3baoRUfJRCOO8+uOfCPXv1zuVj2xacMVsPIfiFdxp9zWw+hLyOUDgjqK1wlnLlZCm13XZuAJ27HUWNGj06uJ6nT4Q0tRXO0IjTFxfb7Xt3HA8fP3SLZcOO0ZjvvCGs12z15QN69OxZWG45QDi0D8+QcOp66kXnfcJp61mqbrIdv+MmTMikl/11uVhL1udcGcLpW2xdsG0Lwjlz1qxcelm/ttz6E/I6QOGMoLbCGcsvv/2aGXFpl1nAdm4AwmlHU5ji9Y1Cge7ofJ1eXQun9lHoy2f+wvyC5zatDcPNlriCEoo8UPjKDWE/kLnwy89p2CeceroVwlZKOO1IuRS27hJHueLqy5aLqVSbj33HafO1bQvCOcMjnBj5hq4ZIa8rFM4IGlo40eGhg8I7Pfh/LNW5AZ9wAuzbrXt1B2qFB7929CIUCSe8gNhtGi2cEDebv41bGzr/IUOH5ey+8M07t9x7XW2HT0SE8S4wVEYpkHbkqxE7whi1Lli4MN0Grx5yfOItZPmKFel2+OjUArbh889Tv47yAAF3ZOKuC/XUo0Aftu4SR7niVsyW++DRwzQsQl1XwtmpqnMaxnvo67ey70sJeR2hcEbQ0MIp9Huvf/pRR23p1btPzoYvdq2tFJOmTEnatit+R1sp6IDxHs/aIaKYerT2IuwIr1JwvL4pTzzU2JsIX0PjK2KbFqD++kMioS7qibqEyq3q3MW5YrP2ugLXTM8mEPI6Y+/5lkKzEk5CCCFNBwpnBBROQgghFM4IKJyEEEIonIQQQggpCYWTEEIIiaAi4eRULSGEEE7VRkDhJIQQQuGMoKGFE4sGYK1UYLcVgT+kYyk0a28sunXvkfnzPBZGwPJtWGDcpgVY+9T+Ib85gbo/e/HMcff+3dx2jb7GwPdfUR/2GuN8grr6v29dUEnb9YHFP6ytrkGbnDVnTsaG84lFK2xaMGXq1AZvo1hoX9pVQ5dNslA4I2ho4Tx89Ei6ChBWnLHLyjUHcIPrFYv0n+R/PPVTLn1d0lidS0y5R44dTeYtqLsl67CakbU1FnIeJk+pnchg0Xprq0tQtzHjxqVh7blm1erVufR1CcqzfnZL0b5jx1qdT1J7KJwRNKZwArlZsPKMuPQ6eOiQW2INI5f3+g9IXULNmj073Q+2iZMmO1ddWNJNr+OKFV/wBHv5yp+puy482WL5Nqx/OvvVU7gs0wb3V+vWr0/3RdlY1cjWW5g2fXpGHDHy1Nt9wulzZyaImzC9ehDSo96oo15CTs4DfuVcVQLy2LVnd85ehK/uIYqE88T3J11eSCO20DUWfMKJzh/nTS/nhzz0yk/6HOH8PnzyKDOilTJDLut86POgw3A6cOvObddu4ZlF77Nt+/aM+zOghRP1EC9DR48fy9h1eMLEicnf1685V2g6f0vHqip3rBK3I3afcEqb8l1n3B8413q5wkOHDyfT3n8/efzsiWvbOh/kgYfimDZK4Wx8KJwRNKZwQqDsurG44TCCW7RkSWYkh/VPIX4Sx02GaSd0xFiSDXEILbaJ70asVavzRwcC/5doINr9Wagz9HHw20PJ7Llzc3bBJ5yCPVaUNXSYf93aS5f/cFOcCGO5O9gljt9ypz9DYCFz5KXXoS2i1HnRFAmnLPCPdWLR+ept9hoLVjjRLqRT/nD+/OTp86cujLVqxU0YfGv+9XeNEwCp/6DBQzLHgnWQfzp9ygkXxM+WbcG+/QcMcAKHYxA72hV+0cZ0/vCGs+yjj5LuPXpm7CKc+vpialV7xbFtYt2GDWUJDO6db3bvytkFn3AKNm8c15df7Ui3oXyE8YAg1wVh+E1FWNpo+w4do9poOcdF6hcKZwS1Fc5Yt2IQTqSB1wv82nVm8VRt9wG2U5VyxHMHFuLWHjNWrFzpnBbr+thOTcDTOaZesbaqXkjcBxYvtx25plzhhMjfuVfzrlCPOnUdd+/Zkyz/+OM07qt/CHtdfO+IDxw6mIweMyZnt8SUC+EMtQeUBSHBg4vdZq+xYM/3gkWLMnGdj4SxCLxMp8OhOJxV2zQAwrlxU96NWgjsC+8xEAs4URc7ZgggWJjCFSG3ZWkgnNjWt1+1aIJSwilhPCziodDmKWCEG3qPCWKEU8c3b9mS3m84frHjQViPlLEPp2qbHxTOCGornLHYqVoLnsytDdhOVW4yn3CGOhwI57Ub13J5S7pyblwsjK4dM0vnLJQrnJhODrkJ0/VAJ/ixGhWWU8dyQCeIvJZ+tCy3zUdMuaERJ0RTFmxHx2rztNdYsMK54pNPMnGdD0bSEA3tPQWjXO0EWxPyvBNCl3X95g0nyjguLXjarZo9RgHCCe83WrSdcD574t1XhzFSxysGm6fQrn2HzLQzRn96e6XCqdHCiSlb/VCGfSiczQ8KZwSvs3BO/+CDzM1YJJzPX754te16zu4DeeK9nIT1O6RNWza70YfPq4ZvqlbchIU6WyucL/59mfFnWgnIv5SrL0tMpxYSTrhsw/s3hM//ciGXp73GAkZY+JXZCHTKq9dWp8M0p80HcXHdpm0S1qJSqXAifwnjuGSUaR8IcM3FhRuuMR6YEJapWrQ77SJO72vDMjOAsK99aZBGnHSjDvhiVrbh2wARNuuZx57Luw/upQ9X2iVekXCevXDOPcDofEpB4Wx8KJwRNBXh3H/wgLtxBLF/8tmnGbtsk1+fcOJ9C7ZjilPS4cMNnQfqocvHzW8/6giBJ3r5fN5+7g+kDC2uGvw1BXa8A8KoE7ZQ52mFEx+/oCNEmvpygeZD16kUIeGUfICeNg9dY+H+w/vOBrEVm7wiwMOOfAAm+D7ywQMK0kOoZHrUlol3l3Y/i6SFQ3b9mkEeBPBO0DpYx/Q+tulzoj8OwjZpK/gYDHF8BKTPA8IYadt8QuCc4G9DSL/+8w257XIcaPc6LmihxXcHsOl3ukXCCTACxz76a94iKJyND4UzgoYWzqbK7r17cjZSAzq1q9f+doiTatJwvK6ismz5ctemMBP0uh5jc4HCGUFLF8558+e7v7ToJ2xCmhr4SMzaCKlLKJwRtHThJIQQQuEkhBBCSBlQOAkhhJAIKhJOTtUSQgjhVG0EFE5CCCEUzggonIQQQiicEVA4CSGEUDgjoHASQgihcEaAJcjg2grMWzA/DWsayz5j1sycrVT6UaPH5Oxjxo7N2SQfX/rJU6a49TytPUQoPcr9cN68nB34ykV6LN5t7cB3zLHpi+yhetZV+qZmZ9uqwXfMsemL7KF6htI3d3tzbVsUzgjg3Fl4/PRJJt7Y9jv37+ZspdJf/ONSzv7Hn5dzNsnHlx7Lf2EZMGsPEUqPcuGyzNqBr1ykv333ds4OfMccm77IHqpnXaVvCnYs6SZhtq0afMccm77IHqpnKH1ztzfXtiXrJbc0KhJOQloKXAuVEGKhcBJSAIWTEGKhcBJSAIWTEGKhcBJSAIWTEGKhcBJSAIWTEGKhcBJSAIWTEGKhcBJCCCERUDgJIYSQCCichBTAqVpCiIXCSUgBFE5CiIXCSUgBFE5CiIXCSUgBFE5CiIXCSUgBFE5CiIXCSUgBFE5CiIXCSUgBEE5CiB/64ySE5EDnYG2EkGoonISQHBROQsJQOAkhOSichIShcBJCclA4CQlD4SSE5KBwEhKGwkkIyUHhJCQMhZMQQgghJaFwEkIIIRFQOAkhhJAIKJyEEEJIBBROQgghJAIKJyEe3u33XtKvf/8MHTp2yqUjpKXRqapz7t7o0/fdXLrXGQonIR4GDx2aW9DapiGkpWLvDQonIcTx+6WLaccwZuzY3HZCWirT3n8/vTfOnDuT2/66Q+EkJECrN9/iaJOQAHJv/O+NVrltrzsUTkIKQMewcPGinJ2Qls7KTz5Jrt+6kbO3BCichBTw+NmTnI0QUk3bdu1ztpYAhZOQAlriNBQhpBgKJyGEEBIBhZMQQgiJgMJJCCGEREDhJIQQQiKgcBJCCCERUDgJIYSQCCichBBCSAQUTpIDq+U8e/HMseyjj3LbNa3btE3D+M/jW63b5NI0V/SxCViGD1i7TYvzUPQfUOSBfex+dU1Vly7J3Qf3cnZhwMBBzhOMtdcGaTtg5OjRue3NgV9//y15/vK5O4ZvjxzObfdR39eyXKRdaWwaTcdOVcnMWbPcSkB2W3Ni6LBhyfgJE3P2+oDCSXLErM2q0w4fMSL5868ruTTlMrqJLaTuOw+fb9qYbN6yJWdH2qvXrrowRBPxIUOH5dIJeCDZvWePCyOdr6yGAMfy2epVOXtd0ZyFc1RE3eEdBG1frmlTYNv27cna9ety9hD13QbrM//bd2+nD6qPnjxO5i9ckEtTl1A4SY6YBh4Szu07vkwmTJyYPHn21N3Aep9de3a7/Y4eP5baTv7wffLinxfuF6xeu8bZV61Zk5bx46mfkr+vX0v3+WDGjOTm7ZvJmXNnM/kvWrw4efnvP8nWL7Zlyjx34XyyZdtWJ1rlLKXnOw9Fwnn/0QMXvnT5j+TrXd+ULZxg5zdfu98p06a548cxHTx0KLn34H7y5lut3bZJU6YkN27ddOcBowTYVqxcmSxYVLOWLvZt175DGgZ79+3LlD1x0uTkwaOHyb4D+3PCuXf/PjfS0jMHyAPHN3vOHHeNFi9dksmviJYinGhbb3d9J9dmhg4fnjx++jj56+/qhyqAdrtu/fo0juvc773+rq336ds3OXT4W3ee7YMkruN3J094Zzx8+IQT1/X4ie8cNr2tu07/8PHD1IZ6oS3cf3g/6dGzp6tr5y5vu23vdOvu2i7a6chRo5xt2vTpaRuSNil5hdrW4aNHMvXAiNjWTaPrjvYvcV1Wz169M/ss//jj5OGTR8mH8+entkVLato20st9CXDNcG/gHqFwkhy+GyhESDh//vWXZN2GDS6Mjv7E9yddGE+CcNeFMG6sdu2r17pEZzBuwoR0KvSNVm9myrh85bILf7N7l/ud9epGg2gijJtWdxBnL5xzv6jLkqVLXfjK1b/cEynyGjR4SFkjY995KBLOHj17OTHC9N6x745HCSeemPV2PHDgHOBGlnMBsccx6A5aPLjoetiycP51HGmQDxxzIyzCiTCmu3z5ID5s+Ah3vSDWtowQLUU45Xz5zhvONdi+Y0cuvQ5jShgPfEiLTtumGTtufDJ4yJBcGSF8wol9u7zd1d0DNh8b1+n19lmzZzsBQds7cuyoi589fy5NIw96CLfv2NEdj7RT36sO2G3b0nV5/5Xw2npZbN0lru14LSFhCKI8cOMhUtwG6od8pMdDMMK/Xfw9+fKr6us3b8ECCifJYxthETqtFU5fOjxRYyoF795sXvYJW+/bpm32Pc3T508zcYiVhHEDYhSG+sgNDeGUvPBrR2E+fOehSDjlF53bqTOnSwon0qJ+6CzREfny00DoJAzRnTFzZppWRoj6CVmwwqm9vRz89pATTnR2d+7dTe121OmrTzm0FOFE5/v/t3em/VUUaRTPZ1DGBRKCQEBQHBWQJUQIi46swWFTBGQRUAYmBERicEYUSAIoKIiIiCwBErKJCZs4b0ad+Vg1fepaneqn6t6kmaRTkvPi/+vuOuc+XbfvvX26qjuAZW3dh2pXdc8IHsdt7bp1jh8jHSyXVlXp0SrWEZz2RYk55viH1Lvv3HJq9IYMzlde/YsezZpt+ZnK7Xx+BCUuELGOzxchb25T2LMR+J3U7O3Zv6xfqB3fWVwcY93+bfvAhfMv//nVW9OubQen3V61fLn+vWI9X3DKPjI4iYP8khTC9i549dVegxNgWgpTP3I/hYLT14ZpKxu0zygv1xpGTpg6NSelrIJz3YYNetmX4ETfcCHhe4hI7ls+wPPejh1xSGJqGlNbsypeduoAGZx2IODEhuDESVIeU/t/vpD96StDJThxfGxs7fyF87oN303ThhEWlpjGfXrCRL2O4FxjTUmaOjixnz33jbPP3pDBWb17t/MZ237Z73x+OzhxjOzgRMjZfvsiTdYv1I4HmjB1m0+XSI/ZtttlcNr9NLMBhYLT9jM4iYP8EhYC065myhGjwNcWLtTrCE6zvm//fn3PA+t4wtOEC+5F2Cd7/FjMU3F26Pj6U7NnTzzlC0yIvBsFiglt3B/MOjgNfQnOQg+SyHrAnJzMlLOczva9BsjgtK/O8Rp7qvb5F17MeX4/adk+WbcvDIXglPfwzbHCaNK+N4jvo+1raW1RN7t+jLfzBadZf3HyZKe9EDI4zWvNTAJuB0gN3y35vZL+QsFp9w2/Pfs3gO8dft9ytinf+8Hxabp2Vb00LXlv0seNttytHHDrzm19sWFqmwuT2/fuxB5czBw7flyv/+Pjf+rpV6xjdsD2m+DEeWvr9m16vWzceAYnccn3Rc4HggqvMfc0TduOnTt1+82ungd6AO5Xot23H0xbov3gp5/obfwIjFf6cc/B1477hfiR4sGF/zc45b4RnL522YcHDc5jnx13ahtwIkQbrupnV1YmtPc/2Kcf1rDbZD8PfJR7WAonU2zj2OKEYYIT955w3xjaqjVrvHXkQxu9MRSCU35O+2tr43VMvZpjJ/9UC232AyuFghNT6T92d+k289BNb/iCExdGCPN///pLYgQMMPVv+mouaI0fbcZfKDhxsYxpfvjln/FgBsP8vs1sRqHvFgJWHtt8IOxNnbfWr4/bMQuGNvxmcL/Vfg0eToR2qelyot32m+AEuCcKDbeaGJzEAV+Ozps/aDZYT5ylQU7VkqGD+e6AP3Jw4r4i3oPvvnF/0NdQGKpgZqq+0b249GH+Vhm3Lcz944GEwUkGBAYnIX5wksdUuLllQVxwfB70wgL/kANei6fcpdZfMDgJIYSQFDA4CSGEkBQwOAkhhJAUMDgJIYQ8EOUVFU7bUIDBSQgh5IEw/5DDUIPBSQgh5IFgcBJCCCEpYHASQgghKWBwEkIIISlgcBJCCCEpYHASQgghKWBwEkIIISlgcBJCCCEpYHASQgghKWBwEkIIISlgcBJCCCEpYHASQgghKXjm2UlO21CAwUkIIYSkgMFJCCGEpIDBSQghhKSAwUkIIYSkgMFJCCGkz+CBoPKKigTTZ8x0fA8zDE5CCCGp+O2/vyWQ+sMOg5MQQkgqVqxcGYfmhYsXHP1hh8FJCCEkNSY4S0c95WgPOwxOQgghqfnbzp3qx1tdTvtQgMFJCCGEpIDBSQghhKSAwUkIIYSkgMFJCCGEpIDBSQghhKSAwUkIIYSkgMFJCCGEpIDBSQghhKSgqGRkqSKEEEJI3+CIkxBCBN9fuqju/+u+uv/zfXX0+DFHt8E/OTe2bJxGaoPB+AkT1NJly5z2rMH/orKsarnTLsHx++uKFU77g7B33/uqtq5OlY0b2M+CI05CCBF89/0FteCVV5x2H+WzZqmWthvqRlurDtuNmzc5noGkvrExsT2jvFw1XW1yfFlz685tNWnSc067zfLXX9fH7POTJ/Ty5dmzHU9fuXf/nnp3xw41p7JSnTn7taP3J1ZwjtJLmazAaAap5zzZ1LG1fHVsLes6UvfVkXqWdeR79tWxtf6sI3VfHalnWcfW8tWxtazrSN1XR+pZ1pHv2VfH1rKuI3VfHdN+/sJ3Ojj7UgfBadfBCVx6fHVGjxmbpy+5Ok+NHuOpkXzP4JtvzyU802fOVJeuXP59H2V62Vsdqcv+lI4a7eiF6jw9YaK6ffe2U0d+lj/9/JMecUJ74cXJauWqVU5/cnqyzpixZU5fcNzz9WdsWc4v68j+5Dy5+r46hqKRpWgkhBBiOHf+WzV/wQKn3cfMaIRnb9+9d1cvEV5Y37xli16C3Am8VH373flYX7qsKn5dc2uLXl5vaY7rmFodP3Tqtnnz5+u2ze+8E9c1oB3B2XTtquq+3a1HwXadhmh02nWrW48G39m6NW7fEtWS/Qf1jQ3qzt270f4vqUOHD8ftvdHe2a4mT5nqtEvsfdm0tbdp7etvzqr2HzpU49FG3Y4l+oMZARxDu45Na1ub47f31dbRrt5480118fIl3Z4L4ugCIQpF2z/qKVwwuP0rKi4ZqXKU6mUyjXMYzSD1nCebOraWr46tZV1H6r46Us+yjnzPvjq21p91pO6rI/Us69havjq2lnUdqfvqSD3LOvI9++rYWtZ1pO6rY9pxwkZA9aXOjCioTn75hfri1Jeqq7tb7dy1K9YwFXnqzOlEnTXRCbtm757Y0x0FGZZd3V1azy1L1eo1a3T7tu3b1Vvr18X9xT7s/pw+81WiPy9Nn65ao+Ax76vuwAHdXjl3nvrk0KfeOps2b3b6g/bLTVfUB7X7dR17Hwb72Jljs/7tDdF+DglPz3E27XPmzo1G9uf1Ot4z+mOOgd2PXI2eOq8tWhQdw7UJ3dTw9Wfh4sXqjbVr9RSu0ZpvtKhZFRV6e9Xq1epIfX1cJ1f/TTV7TqX+XE0dG97jJIQQwVdfn1Fz581z2n1MnzFDTZk6VY+wpFa1fLn6sK4u0fbxJwfV6jdyoQha21vVpOf+rG523dTbZrk6OqFjeeyz49Fos0PVNzTE2PW+PH0qsT0tCk6Mxsz27j25kN66bZuu7avz9saN8brZv6F6d7Vu2/n3nguCQsjXF0J67W2pAYwUa+s+VC/Pnu3oclv6m280x+3Xm5v1w0tYX7J0qTrSkAvOqdOmJfwITlkTWCNOQggh4NRXp6MR2lyn3cf0KKhkm2FZVZWqra1NtGGkdSYKZrPdebPTu8T9PiwxYmpobIj9mO61611vuZ7YxogT9z3NdnVNjV6OG/+0nsI17c9Oei5e//jgwXjd7B9s3LTJ256P11esUA1HG532fKAmggjrCLK2DjNS9u/PbpO63JZtW7ZujdevRsdh4jPP6vXFS5aoQ0cO6/W6jw4k/CdOnnBqAic4c28il6o9y3A8Ug/PI99PaB6pZ+eRfQ3NI/XwPPL9hOaRelge+X4KeTCKm1M5t6DHLDHi9Hkw0mzrbFftHR2q7kBdQr9yrUmPBK9FIx+M5FCnPRodQTPLFStXxvvAPc/jn3+u/0wGI1C7VkdnRxRWR9Xlq1d0+GDUhKlmo++qro7r4GnTs+fO6RH1xaiW8aCP+/Z/oC41XdH14EX72XNntW/7e++pq83Xnfdu98PU6c1ja4uj0R5egylkvG88hQsPjh36gaV97HAcTnxxUtXs3evsyxw3m+stLXrUWLP3fXW4/kjcjiloE5yLFi9Rnx4+pOtMnjIlro8w/Sw65rLPWEbBWaJsSkbiQ08SkkfqoXmkHppH6ll6pB6aR+qheaQemkfqoXmkXsiDk21lZWVBT1/qFPLM13/ukl+XdcaMHatyJ2/XM2/+AjVh4sQ+1cFToaPHjEnoeMI3X38wMl24aFFCkx4D/qykN4/UAUbhhTy2hnArGze+oMeug2l0jLYLeWxM/UIe74jT0JOyrsdoPV7XMxB1pO6rI/Us69ha/jryPbuegaojdX8dqfdPHdnXfJ7BqiN1Xx2pZ1nH1vLXke/Z9QxUHan760g9uzq2lq9OUsvvGYg6UvfVkXp/1ZF99dfp0bKuI3V/HakPXB1PcLqE5JF6aB6ph+aRepYeqYfmkXpoHqmH5pF6aB6ph+aRepYeqYfmkfpge5zgJIQQQkh+GJyEEEJICopGFJcoQgghhPQNBichhBCSgqIRI4pVkhIPIXmkHppH6qF5pJ6lR+qheaQemkfqoXmkHppH6qF5pJ6lR+qheaQ+uB6OOAkhhJAUFA0XaVpc7CLTVupZeqQemkfqoXmknqVH6qF5pB6aR+qheaQemkfqoXmknqVH6qF5pD7YnqJhw4Y5aUoIIYQQP0WPPjpM/emxx6ONYkIIIYT0gg5O8PjjTyjfTdAcaLeRepYeqYfmkXpoHqln6ZF6aB6ph+aRemgeqYfmkXpoHqln6ZF6aB6pD64nDs6ekWeJGg5RLG2klqXHBz1/DI/UQvP4oOfh8UgtNI8PesL0RMH5qEoyTD322BNq+PBiixECW8vaI/XQPFIPzSP1LD1SD80j9dA8Ug/NI/XQPFIPzSP1LD1SD80j9cH1FD3yyDBlY49A8eAQpnCffHKEejIyG/AkrsTWB9Ij9dA8Ug/NI/UsPVIPzSP10DxSD80j9dA8Ug/NI/UsPVIPzSP1wfYkpmoJIYQQUhjvVK1LSB6ph+aRemgeqWfpkXpoHqmH5pF6aB6ph+aRemgeqWfpkXpoHqkPrud/uOMVGR3Xqz4AAAAASUVORK5CYII=>