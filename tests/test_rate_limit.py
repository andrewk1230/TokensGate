from __future__ import annotations

from app import rate_limit as rl_mod
from app.rate_limit import check_and_increment


def test_under_limit_allowed():
    for i in range(5):  # limit is 5/min per conftest
        decision = check_and_increment("client-a", estimated_tokens=10)
        assert decision.allowed, f"request {i} should be allowed"


def test_over_request_limit_returns_429():
    for _ in range(5):
        check_and_increment("client-b", estimated_tokens=1)
    decision = check_and_increment("client-b", estimated_tokens=1)
    assert decision.allowed is False
    assert decision.reason == "requests"
    assert decision.retry_after_seconds > 0


def test_token_limit_independent_of_request_count():
    # limit is 1000 tokens/min; one request burning 1500 should trip it
    decision = check_and_increment("client-c", estimated_tokens=1500)
    assert decision.allowed is False
    assert decision.reason == "tokens"


def test_isolation_between_clients():
    for _ in range(5):
        check_and_increment("client-x", estimated_tokens=1)
    decision_x = check_and_increment("client-x", estimated_tokens=1)
    decision_y = check_and_increment("client-y", estimated_tokens=1)
    assert decision_x.allowed is False
    assert decision_y.allowed is True


def test_decision_exposes_counters():
    decision = check_and_increment("client-d", estimated_tokens=42)
    assert decision.request_count == 1
    assert decision.token_count == 42
    assert decision.limit_requests == 5
    assert decision.limit_tokens == 1000


def test_rejected_request_does_not_count_against_bucket():
    """A burst that hits the ceiling should not poison the bucket with
    the rejected attempts. Future allowed requests should still see only
    the originally-recorded count."""
    for _ in range(5):
        check_and_increment("client-e", estimated_tokens=10)
    # 5 rejected attempts in a row
    for _ in range(5):
        d = check_and_increment("client-e", estimated_tokens=10)
        assert d.allowed is False
    # Bucket should still report 5 (the 5 successful), not 10
    # We can't allow another req to verify (already at limit), but the
    # decision's `request_count` reflects current state.
    d = check_and_increment("client-e", estimated_tokens=10)
    assert d.request_count == 5


# ----------------------------------------------------------------------------
# Sliding-window regression tests — these are the Phase 2.5 fix.
# ----------------------------------------------------------------------------

def test_sliding_window_releases_old_entries(monkeypatch):
    """After the 60s window slides past the original requests, new requests
    in a fresh window must be allowed. This is the standard sliding behavior."""
    clock = [1_700_000_000_000]  # virtual time in ms

    def fake_now_ms() -> int:
        return clock[0]

    monkeypatch.setattr(rl_mod, "_now_ms", fake_now_ms)

    # Saturate the bucket
    for _ in range(5):
        assert check_and_increment("drip", estimated_tokens=10).allowed

    # Immediately after: should be limited
    assert check_and_increment("drip", estimated_tokens=10).allowed is False

    # Advance clock 61 seconds — original 5 requests are now outside the window
    clock[0] += 61_000

    # Fresh window: should allow again
    decision = check_and_increment("drip", estimated_tokens=10)
    assert decision.allowed is True
    assert decision.request_count == 1  # only the new request remains in window


def test_slow_drip_is_caught(monkeypatch):
    """REGRESSION: this is the exact bug we found in step 8 of manual testing.

    105 requests spaced 1.7s apart spanned ~3 minutes under the old
    fixed-window implementation, escaping the 100/min limit because each
    calendar minute saw only ~35 requests.

    Under the sliding window, by the time we get to request 6 within 60s,
    we MUST see a 429 regardless of how the requests are spaced.
    """
    clock = [1_700_000_000_000]

    monkeypatch.setattr(rl_mod, "_now_ms", lambda: clock[0])

    # 5 requests spaced 11 seconds apart — under the old fixed-window
    # implementation, these could span a calendar minute boundary and the
    # 6th could escape. Under sliding-window, the 6th MUST be limited
    # because all 5 are still within the trailing 60-second window.
    for i in range(5):
        d = check_and_increment("drip-slow", estimated_tokens=10)
        assert d.allowed, f"request {i} should be allowed (drip)"
        clock[0] += 11_000  # advance 11s between requests

    # 6th request at t=55s — all 5 previous are still in the 60s window
    decision = check_and_increment("drip-slow", estimated_tokens=10)
    assert decision.allowed is False, (
        "sliding-window regression: 6 requests in trailing 60s must be limited"
    )
    assert decision.reason == "requests"


def test_token_sum_uses_sliding_window(monkeypatch):
    """Token-axis sliding behavior. Same logic as request-axis but verifies
    the token-sum path runs through the sliding cleanup."""
    clock = [1_700_000_000_000]
    monkeypatch.setattr(rl_mod, "_now_ms", lambda: clock[0])

    # Burn 800 tokens (under 1000 limit)
    assert check_and_increment("tok-client", estimated_tokens=800).allowed

    # 300 more would push to 1100 — over limit
    assert check_and_increment("tok-client", estimated_tokens=300).allowed is False

    # Slide 61s ahead — original 800 expires
    clock[0] += 61_000

    # Now 300 tokens fits cleanly
    decision = check_and_increment("tok-client", estimated_tokens=300)
    assert decision.allowed
    assert decision.token_count == 300


def test_retry_after_reflects_oldest_entry(monkeypatch):
    """retry_after_seconds should be 'when does the oldest in-window request
    expire' — NOT just the full window length."""
    clock = [1_700_000_000_000]
    monkeypatch.setattr(rl_mod, "_now_ms", lambda: clock[0])

    # First request locks in oldest_score = t=0
    check_and_increment("retry-client", estimated_tokens=10)

    # Advance 40s, then saturate the rest
    clock[0] += 40_000
    for _ in range(4):
        check_and_increment("retry-client", estimated_tokens=10)

    # Now we're at the limit. retry_after should be ~20s (60s window
    # minus the 40s that have passed since the oldest entry).
    decision = check_and_increment("retry-client", estimated_tokens=10)
    assert decision.allowed is False
    # Allow some slack; the math is 60 - 40 = 20 give or take a second
    assert 18 <= decision.retry_after_seconds <= 22, (
        f"expected ~20s retry, got {decision.retry_after_seconds}s"
    )
