"""End-to-end-ish tests for the FastAPI endpoint.

We stub the Anthropic client so tests don't hit the network and don't burn
API credits. The stub returns a canned response shaped like the real SDK.
"""

from types import SimpleNamespace

from fastapi.testclient import TestClient


def _fake_anthropic_response(text: str, input_tokens: int = 17, output_tokens: int = 9):
    return SimpleNamespace(
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens),
    )


class _FakeAnthropic:
    def __init__(self, text: str = "hello back"):
        self._text = text
        self.calls = 0

        outer = self

        class _Messages:
            def create(self, **kwargs):  # noqa: ANN001
                outer.calls += 1
                return _fake_anthropic_response(outer._text)

        self.messages = _Messages()


def _client(monkeypatch, fake_anthropic=None):
    """Build a TestClient with deps patched.

    api.py now resolves anthropic_client at call time from app.deps, so
    patching the singleton in one place is sufficient.
    """
    fake_anthropic = fake_anthropic or _FakeAnthropic()
    from app import deps as deps_mod
    monkeypatch.setattr(deps_mod, "anthropic_client", fake_anthropic)
    from main import app
    return TestClient(app), fake_anthropic


def test_health(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "healthy"


def test_chat_completions_basic(monkeypatch):
    client, fake = _client(monkeypatch)
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Client-ID": "alice"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["choices"][0]["message"]["content"] == "hello back"
    assert body["usage"]["prompt_tokens"] == 17
    assert body["usage"]["completion_tokens"] == 9
    assert r.headers["X-Cache"] == "MISS"
    assert fake.calls == 1


def test_cache_hit_on_second_identical_request(monkeypatch):
    client, fake = _client(monkeypatch)
    payload = {"messages": [{"role": "user", "content": "ping"}]}
    headers = {"X-Client-ID": "alice"}

    r1 = client.post("/v1/chat/completions", json=payload, headers=headers)
    r2 = client.post("/v1/chat/completions", json=payload, headers=headers)

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.headers["X-Cache"] == "MISS"
    assert r2.headers["X-Cache"] == "HIT"
    # Anthropic should have been called exactly once
    assert fake.calls == 1


def test_routing_auto_picks_cheap_for_small(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "short"}]},
        headers={"X-Client-ID": "alice", "X-Route-Strategy": "auto"},
    )
    assert r.status_code == 200
    from app.config import CHEAP_MODEL
    assert r.headers["X-TokensGate-Model"] == CHEAP_MODEL


def test_routing_forced_expensive(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "short"}]},
        headers={"X-Client-ID": "alice", "X-Route-Strategy": "expensive"},
    )
    assert r.status_code == 200
    from app.config import EXPENSIVE_MODEL
    assert r.headers["X-TokensGate-Model"] == EXPENSIVE_MODEL


def test_rate_limit_returns_429(monkeypatch):
    client, _ = _client(monkeypatch)
    headers = {"X-Client-ID": "flooder"}
    # First 5 (the test limit from conftest) should succeed
    for i in range(5):
        # Use distinct content to avoid cache hits inflating counts oddly
        r = client.post(
            "/v1/chat/completions",
            json={"messages": [{"role": "user", "content": f"req-{i}"}]},
            headers=headers,
        )
        assert r.status_code == 200, f"request {i}: {r.text}"
    # 6th should be rate-limited
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "req-6"}]},
        headers=headers,
    )
    assert r.status_code == 429
    assert r.json()["error"]["type"] == "rate_limit_exceeded"
    assert "Retry-After" in r.headers


def test_metrics_endpoint(monkeypatch):
    client, _ = _client(monkeypatch)
    client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "metric-test"}]},
        headers={"X-Client-ID": "alice"},
    )
    r = client.get("/metrics")
    assert r.status_code == 200
    m = r.json()
    assert m["total_requests"] >= 1
    assert m["total_input_tokens"] >= 1
    assert "cache" in m
    # Phase 3: metrics endpoint should surface circuit-breaker state too.
    assert "circuit_breakers" in m
    assert "anthropic" in m["circuit_breakers"]
    assert "ollama" in m["circuit_breakers"]


# ----------------------------------------------------------------------------
# Phase 3: Circuit breaker + Ollama failover integration tests
# ----------------------------------------------------------------------------

def test_response_includes_phase3_headers(monkeypatch):
    """X-TokensGate-Provider, -Fallback, -CB-* should appear on every response."""
    client, _ = _client(monkeypatch)
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "hi"}]},
        headers={"X-Client-ID": "alice"},
    )
    assert r.status_code == 200
    assert r.headers["X-TokensGate-Provider"] == "anthropic"
    assert r.headers["X-TokensGate-Fallback"] == "false"
    assert r.headers["X-TokensGate-CB-Anthropic"] == "closed"
    assert r.headers["X-TokensGate-CB-Ollama"] == "closed"
    assert "anthropic:ok" in r.headers["X-TokensGate-Attempts"]


def test_failover_to_ollama_on_anthropic_retryable_error(monkeypatch):
    """When Anthropic raises a retryable error, gateway should fall over to Ollama
    and surface provider=ollama in the response + headers."""
    from app import providers as prov_mod

    # Make the anthropic provider fail retryably
    def ant_fail(**kwargs):  # noqa: ARG001
        raise prov_mod.ProviderError(
            "simulated 503", status_code=503, is_retryable=True,
            provider=prov_mod.ANTHROPIC_TARGET,
        )

    # Ollama succeeds with a canned response
    def ol_ok(**kwargs):  # noqa: ARG001
        return prov_mod.CompletionResult(
            text="from ollama", input_tokens=3, output_tokens=2,
            model="llama-test", provider=prov_mod.OLLAMA_TARGET, latency_ms=5.0,
        )

    monkeypatch.setattr(prov_mod.anthropic_provider, "generate", ant_fail)
    monkeypatch.setattr(prov_mod.ollama_provider, "generate", ol_ok)

    client, _ = _client(monkeypatch)
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "needs fallback"}]},
        headers={"X-Client-ID": "alice"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "ollama"
    assert body["choices"][0]["message"]["content"] == "from ollama"
    # Ollama is local → free
    assert body["cost"]["total_cost"] == 0.0
    # Headers should mark the fallback explicitly
    assert r.headers["X-TokensGate-Provider"] == "ollama"
    assert r.headers["X-TokensGate-Fallback"] == "true"
    # Attempts log should show both legs
    assert "anthropic:error" in r.headers["X-TokensGate-Attempts"]
    assert "ollama:ok" in r.headers["X-TokensGate-Attempts"]


def test_503_when_both_providers_fail(monkeypatch):
    """If both Anthropic AND Ollama fail, gateway returns the failover error."""
    from app import providers as prov_mod

    def ant_fail(**kwargs):  # noqa: ARG001
        raise prov_mod.ProviderError(
            "anthropic down", status_code=502, is_retryable=True,
            provider=prov_mod.ANTHROPIC_TARGET,
        )

    def ol_fail(**kwargs):  # noqa: ARG001
        raise prov_mod.ProviderError(
            "ollama down", status_code=500, is_retryable=True,
            provider=prov_mod.OLLAMA_TARGET,
        )

    monkeypatch.setattr(prov_mod.anthropic_provider, "generate", ant_fail)
    monkeypatch.setattr(prov_mod.ollama_provider, "generate", ol_fail)

    client, _ = _client(monkeypatch)
    r = client.post(
        "/v1/chat/completions",
        json={"messages": [{"role": "user", "content": "doomed"}]},
        headers={"X-Client-ID": "alice"},
    )
    assert r.status_code in (500, 502, 503)
    body = r.json()
    assert body["error"]["type"] == "upstream_unavailable"
    assert "circuit_breakers" in body["error"]


def test_health_includes_circuit_breaker_state(monkeypatch):
    client, _ = _client(monkeypatch)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert "circuit_breakers" in body
    assert "anthropic" in body["circuit_breakers"]
    assert "ollama" in body["circuit_breakers"]
    assert body["circuit_breakers"]["anthropic"]["state"] == "closed"


# ----------------------------------------------------------------------------
# Phase 4: Dashboard
# ----------------------------------------------------------------------------

def test_dashboard_returns_html(monkeypatch):
    """GET /dashboard should return a self-contained HTML monitoring page."""
    client, _ = _client(monkeypatch)
    r = client.get("/dashboard")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "TokensGate Dashboard" in r.text
    assert "circuit" in r.text.lower()
    assert "cache" in r.text.lower()
