"""Tests for the Phase 3 circuit breaker.

We exercise the state machine end-to-end using monkeypatched virtual time —
same pattern as the rate-limit sliding-window tests. No real sleeps, all
deterministic.

Defaults in this suite are pulled from app.config (5 failures / 30s window /
60s cooldown). If those env vars change, the assertions below should adapt
automatically because we read CB_FAILURE_THRESHOLD / CB_WINDOW_SECONDS /
CB_COOLDOWN_SECONDS at test time.
"""

from __future__ import annotations

import pytest

from app import circuit_breaker as cb
from app.circuit_breaker import CircuitState
from app.config import (
    CB_COOLDOWN_SECONDS,
    CB_FAILURE_THRESHOLD,
    CB_WINDOW_SECONDS,
)


TARGET = "test-target"


@pytest.fixture
def virtual_clock(monkeypatch):
    """Monkeypatch cb._now_ms() with a clock list so tests can advance time."""
    clock = [1_700_000_000_000]
    monkeypatch.setattr(cb, "_now_ms", lambda: clock[0])
    return clock


# ---------------------------------------------------------------------------
# CLOSED state behavior
# ---------------------------------------------------------------------------

def test_default_state_is_closed_and_allows():
    allowed, snap = cb.allow_request(TARGET)
    assert allowed is True
    assert snap.state == CircuitState.CLOSED
    assert snap.failures_in_window == 0


def test_isolated_failures_do_not_trip(virtual_clock):
    """Fewer-than-threshold failures should leave the circuit CLOSED."""
    for _ in range(CB_FAILURE_THRESHOLD - 1):
        cb.record_failure(TARGET, status_code=500)
    snap = cb.get_snapshot(TARGET)
    assert snap.state == CircuitState.CLOSED
    assert snap.failures_in_window == CB_FAILURE_THRESHOLD - 1


# ---------------------------------------------------------------------------
# CLOSED → OPEN transition
# ---------------------------------------------------------------------------

def test_threshold_trip_opens_circuit(virtual_clock):
    """At exactly the threshold, the circuit must trip to OPEN."""
    for _ in range(CB_FAILURE_THRESHOLD):
        cb.record_failure(TARGET, status_code=503)
    snap = cb.get_snapshot(TARGET)
    assert snap.state == CircuitState.OPEN
    assert snap.failures_in_window >= CB_FAILURE_THRESHOLD


def test_open_circuit_blocks_requests(virtual_clock):
    for _ in range(CB_FAILURE_THRESHOLD):
        cb.record_failure(TARGET, status_code=503)
    allowed, snap = cb.allow_request(TARGET)
    assert allowed is False
    assert snap.state == CircuitState.OPEN
    assert snap.cooldown_remaining_s > 0


# ---------------------------------------------------------------------------
# Rolling window (the key Phase 3 property)
# ---------------------------------------------------------------------------

def test_failures_decay_outside_window(virtual_clock):
    """4 failures, slide past window, 4 more → must NOT trip (old ones decayed).

    With CB_FAILURE_THRESHOLD=5, four failures in window 1 + four in window 2
    is 8 total but only 4 in the current trailing window — should stay CLOSED.
    """
    if CB_FAILURE_THRESHOLD < 5:
        pytest.skip("test assumes threshold >= 5")
    for _ in range(CB_FAILURE_THRESHOLD - 1):
        cb.record_failure(TARGET, status_code=503)

    # Slide past the window
    virtual_clock[0] += (CB_WINDOW_SECONDS + 1) * 1000

    # Add (threshold - 1) more — total in trailing window is now (threshold-1)
    for _ in range(CB_FAILURE_THRESHOLD - 1):
        cb.record_failure(TARGET, status_code=503)

    snap = cb.get_snapshot(TARGET)
    assert snap.state == CircuitState.CLOSED, (
        f"old failures should have decayed; got state={snap.state}"
    )


# ---------------------------------------------------------------------------
# OPEN → HALF_OPEN transition (cooldown expiry)
# ---------------------------------------------------------------------------

def test_cooldown_promotes_to_half_open(virtual_clock):
    """After the cooldown elapses, the next allow_request flips OPEN → HALF_OPEN."""
    for _ in range(CB_FAILURE_THRESHOLD):
        cb.record_failure(TARGET, status_code=503)
    assert cb.get_snapshot(TARGET).state == CircuitState.OPEN

    # Still in cooldown
    allowed, _ = cb.allow_request(TARGET)
    assert allowed is False

    # Advance past the cooldown
    virtual_clock[0] += (CB_COOLDOWN_SECONDS + 1) * 1000

    allowed, snap = cb.allow_request(TARGET)
    assert allowed is True, "cooldown elapsed → canary must be allowed"
    assert snap.state == CircuitState.HALF_OPEN


# ---------------------------------------------------------------------------
# HALF_OPEN canary outcomes
# ---------------------------------------------------------------------------

def test_half_open_success_closes_circuit(virtual_clock):
    """Successful canary closes circuit + clears failure log."""
    for _ in range(CB_FAILURE_THRESHOLD):
        cb.record_failure(TARGET, status_code=503)
    virtual_clock[0] += (CB_COOLDOWN_SECONDS + 1) * 1000

    cb.allow_request(TARGET)  # transitions OPEN → HALF_OPEN
    snap = cb.record_success(TARGET)

    assert snap.state == CircuitState.CLOSED
    assert snap.failures_in_window == 0


def test_half_open_failure_reopens_circuit_with_fresh_cooldown(virtual_clock):
    """Failed canary re-opens with a fresh cooldown — opened_at_ms should advance."""
    for _ in range(CB_FAILURE_THRESHOLD):
        cb.record_failure(TARGET, status_code=503)
    first_open = cb.get_snapshot(TARGET).opened_at_ms

    # Wait out cooldown, send canary, fail it
    virtual_clock[0] += (CB_COOLDOWN_SECONDS + 1) * 1000
    cb.allow_request(TARGET)  # → HALF_OPEN
    snap = cb.record_failure(TARGET, status_code=503)

    assert snap.state == CircuitState.OPEN
    assert snap.opened_at_ms is not None and first_open is not None
    assert snap.opened_at_ms > first_open, "fresh cooldown should restart timer"


# ---------------------------------------------------------------------------
# Reset + snapshot bundling
# ---------------------------------------------------------------------------

def test_reset_clears_state(virtual_clock):
    for _ in range(CB_FAILURE_THRESHOLD):
        cb.record_failure(TARGET, status_code=503)
    cb.reset(TARGET)
    snap = cb.get_snapshot(TARGET)
    assert snap.state == CircuitState.CLOSED
    assert snap.failures_in_window == 0
    assert snap.opened_at_ms is None


def test_get_all_snapshots_bundles_targets(virtual_clock):
    cb.record_failure("alpha", status_code=500)
    cb.record_failure("beta", status_code=502)
    out = cb.get_all_snapshots(["alpha", "beta"])
    assert set(out.keys()) == {"alpha", "beta"}
    assert all("state" in v and "failures_in_window" in v for v in out.values())


def test_trip_counter_increments_per_open(virtual_clock):
    """Every CLOSED→OPEN transition should bump the trip counter."""
    # Trip once
    for _ in range(CB_FAILURE_THRESHOLD):
        cb.record_failure(TARGET, status_code=503)
    out1 = cb.get_all_snapshots([TARGET])
    assert out1[TARGET]["total_trips"] == 1

    # Recover, then trip again
    virtual_clock[0] += (CB_COOLDOWN_SECONDS + 1) * 1000
    cb.allow_request(TARGET)
    cb.record_success(TARGET)
    for _ in range(CB_FAILURE_THRESHOLD):
        cb.record_failure(TARGET, status_code=503)
    out2 = cb.get_all_snapshots([TARGET])
    assert out2[TARGET]["total_trips"] == 2
