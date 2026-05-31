"""Shared pytest fixtures.

We use fakeredis so unit tests don't need a real Redis instance. The
project's `app.deps.redis_client` is monkey-patched at the start of every
test session — modules that imported it earlier still pick up the patch
because Python re-resolves the name on each access via the module dict.
"""

from __future__ import annotations

import os

# Set env BEFORE importing app modules so config picks defaults up cleanly.
os.environ.setdefault("CLAUDE_API_KEY", "test-key")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379")
os.environ.setdefault("RATE_LIMIT_REQUESTS_PER_MIN", "5")
os.environ.setdefault("RATE_LIMIT_TOKENS_PER_MIN", "1000")
os.environ.setdefault("ROUTER_THRESHOLD_TOKENS", "500")

import fakeredis  # noqa: E402
import pytest  # noqa: E402

from app import cache, circuit_breaker, deps, metrics, rate_limit  # noqa: E402


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch):
    """Replace the real Redis client with a fakeredis instance, per test."""
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(deps, "redis_client", fake)
    monkeypatch.setattr(cache, "redis_client", fake)
    monkeypatch.setattr(rate_limit, "redis_client", fake)
    monkeypatch.setattr(metrics, "redis_client", fake)
    monkeypatch.setattr(circuit_breaker, "redis_client", fake)
    yield fake
    fake.flushall()
