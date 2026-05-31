"""Per-target circuit breaker with rolling failure window.

Phase 3 of the execution plan. One breaker instance per upstream target
("anthropic", "ollama", ...). State lives in Redis so it survives restarts
and is shared across multiple gateway replicas.

STATE MACHINE
=============

  CLOSED     normal traffic to target
     │       on a retryable failure: ZADD timestamp to fails ZSET
     │       if (failures in trailing CB_WINDOW_SECONDS) >= CB_FAILURE_THRESHOLD
     ▼       → trip
  OPEN       all traffic skips target; cooldown ticks
     │
     │       cooldown elapsed (CB_COOLDOWN_SECONDS since opened_at)
     ▼
  HALF_OPEN  next request becomes a canary
             canary success → CLOSED, clear failure log
             canary failure → OPEN, fresh cooldown

REDIS KEYS (per target T)
=========================
  cb:fails:T        ZSET   score = failure timestamp ms, member = "{uuid}:{code}"
  cb:state:T        STR    "closed" | "open" | "half_open"
  cb:opened_at:T    STR    epoch ms when current OPEN started
  cb:totals:T:*     INT    INCR counters for /metrics observability

ROLLING-WINDOW DETAIL
=====================
Same shape as the Phase 2.5 sliding-window rate limiter — ZSET keyed by ms
timestamp, ZREMRANGEBYSCORE drops stale entries on every failure record,
ZCARD gives the in-window count. O(log N) per op, microseconds at our scale.

TESTABILITY
===========
`_now_ms()` is the only clock entry point. Tests monkeypatch it to advance
virtual time without sleeping. Same shim pattern as rate_limit.py.

FAIL-OPEN DEFAULTS
==================
If Redis is down or the breaker is disabled, `allow_request()` returns True
and `record_*()` are no-ops. The gateway must keep serving even if its own
state store is unreachable — fail-safe, not fail-shut.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from app.config import (
    CB_COOLDOWN_SECONDS,
    CB_FAILURE_THRESHOLD,
    CB_WINDOW_SECONDS,
    CIRCUIT_BREAKER_ENABLED,
)
from app.deps import logger, redis_client


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class BreakerSnapshot:
    """Read-only view of a breaker's current condition."""
    target: str
    state: CircuitState
    failures_in_window: int
    opened_at_ms: Optional[int]
    cooldown_remaining_s: int


# ---------------------------------------------------------------------------
# Time + key helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    """Single point of truth for time. Tests monkeypatch this."""
    return int(time.time() * 1000)


def _fails_key(target: str) -> str:
    return f"cb:fails:{target}"


def _state_key(target: str) -> str:
    return f"cb:state:{target}"


def _opened_key(target: str) -> str:
    return f"cb:opened_at:{target}"


def _trip_counter_key(target: str) -> str:
    return f"cb:totals:{target}:trips"


def _read_state(target: str) -> CircuitState:
    if not redis_client:
        return CircuitState.CLOSED
    try:
        raw = redis_client.get(_state_key(target)) or "closed"
    except Exception:  # noqa: BLE001
        return CircuitState.CLOSED
    if raw in {"closed", "open", "half_open"}:
        return CircuitState(raw)
    return CircuitState.CLOSED


def _snapshot(
    target: str,
    state: CircuitState,
    *,
    cooldown_remaining_ms: Optional[int] = None,
) -> BreakerSnapshot:
    if not redis_client:
        return BreakerSnapshot(target, state, 0, None, 0)
    try:
        failures = int(redis_client.zcard(_fails_key(target)) or 0)
        opened_at_raw = redis_client.get(_opened_key(target))
        opened_at_ms = int(opened_at_raw) if opened_at_raw else None
    except Exception:  # noqa: BLE001
        failures, opened_at_ms = 0, None

    cooldown_s = 0
    if state == CircuitState.OPEN and opened_at_ms is not None:
        if cooldown_remaining_ms is None:
            cooldown_remaining_ms = (
                opened_at_ms + CB_COOLDOWN_SECONDS * 1000
            ) - _now_ms()
        cooldown_s = max(0, cooldown_remaining_ms // 1000)

    return BreakerSnapshot(target, state, failures, opened_at_ms, cooldown_s)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def allow_request(target: str) -> Tuple[bool, BreakerSnapshot]:
    """Should this request go to ``target``?

    Returns ``(allowed, snapshot)``. If ``allowed`` is ``False``, the caller
    must skip this target and use a fallback (or fail). If the breaker was
    OPEN and the cooldown has expired, this call atomically transitions the
    breaker to HALF_OPEN and returns ``True`` — the resulting request is the
    canary that decides the next transition.

    Fail-open: if the breaker is disabled or Redis is unreachable, returns
    ``(True, default_snapshot)``.
    """
    if not CIRCUIT_BREAKER_ENABLED or not redis_client:
        return True, BreakerSnapshot(target, CircuitState.CLOSED, 0, None, 0)

    state = _read_state(target)

    if state == CircuitState.CLOSED:
        return True, _snapshot(target, state)

    if state == CircuitState.HALF_OPEN:
        # Half-open: any caller through here is the canary. Whether they
        # call record_success or record_failure decides the next state.
        return True, _snapshot(target, state)

    # state == OPEN
    try:
        opened_at_raw = redis_client.get(_opened_key(target))
        opened_at_ms = int(opened_at_raw) if opened_at_raw else 0
    except Exception:  # noqa: BLE001
        opened_at_ms = 0

    cooldown_remaining_ms = (
        opened_at_ms + CB_COOLDOWN_SECONDS * 1000
    ) - _now_ms()

    if cooldown_remaining_ms <= 0:
        # Cooldown elapsed → promote to HALF_OPEN, allow the canary.
        try:
            redis_client.set(_state_key(target), CircuitState.HALF_OPEN.value)
        except Exception:  # noqa: BLE001
            pass
        logger.info(
            "CB %s: OPEN → HALF_OPEN (cooldown elapsed; sending canary)",
            target,
        )
        return True, _snapshot(target, CircuitState.HALF_OPEN)

    return False, _snapshot(
        target,
        state,
        cooldown_remaining_ms=cooldown_remaining_ms,
    )


def record_failure(target: str, status_code: Optional[int] = None) -> BreakerSnapshot:
    """Record a retryable failure. May trip the circuit.

    HALF_OPEN canary failures re-OPEN the circuit with a fresh cooldown.
    CLOSED → OPEN transition fires if in-window failures ≥ threshold.
    """
    if not CIRCUIT_BREAKER_ENABLED or not redis_client:
        return BreakerSnapshot(target, CircuitState.CLOSED, 0, None, 0)

    now = _now_ms()
    window_start_ms = now - CB_WINDOW_SECONDS * 1000
    fails_key = _fails_key(target)
    state_key = _state_key(target)
    opened_key = _opened_key(target)

    try:
        pipe = redis_client.pipeline()
        pipe.zadd(fails_key, {f"{uuid.uuid4().hex}:{status_code or 0}": now})
        pipe.zremrangebyscore(fails_key, 0, window_start_ms)
        pipe.expire(fails_key, CB_WINDOW_SECONDS * 2)
        pipe.zcard(fails_key)
        results = pipe.execute()
        failures_in_window = int(results[-1])
    except Exception as exc:  # noqa: BLE001
        logger.warning("CB %s: failure-record error %s; fail-open", target, exc)
        return BreakerSnapshot(target, CircuitState.CLOSED, 0, None, 0)

    state = _read_state(target)

    # Canary in HALF_OPEN just failed → straight back to OPEN
    if state == CircuitState.HALF_OPEN:
        try:
            redis_client.set(state_key, CircuitState.OPEN.value)
            redis_client.set(opened_key, str(now))
            redis_client.incr(_trip_counter_key(target))
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "CB %s: HALF_OPEN canary failed (status=%s) → OPEN",
            target, status_code,
        )
        return BreakerSnapshot(
            target, CircuitState.OPEN, failures_in_window, now, CB_COOLDOWN_SECONDS,
        )

    # Closed: trip if threshold crossed
    if state == CircuitState.CLOSED and failures_in_window >= CB_FAILURE_THRESHOLD:
        try:
            redis_client.set(state_key, CircuitState.OPEN.value)
            redis_client.set(opened_key, str(now))
            redis_client.incr(_trip_counter_key(target))
        except Exception:  # noqa: BLE001
            pass
        logger.warning(
            "CB %s: CLOSED → OPEN (%d failures in %ds window, last status=%s)",
            target, failures_in_window, CB_WINDOW_SECONDS, status_code,
        )
        return BreakerSnapshot(
            target, CircuitState.OPEN, failures_in_window, now, CB_COOLDOWN_SECONDS,
        )

    return _snapshot(target, state)


def record_success(target: str) -> BreakerSnapshot:
    """Record a success. HALF_OPEN canary success → CLOSED + clear failures."""
    if not CIRCUIT_BREAKER_ENABLED or not redis_client:
        return BreakerSnapshot(target, CircuitState.CLOSED, 0, None, 0)

    state = _read_state(target)

    if state == CircuitState.HALF_OPEN:
        try:
            redis_client.set(_state_key(target), CircuitState.CLOSED.value)
            redis_client.delete(_fails_key(target))
            redis_client.delete(_opened_key(target))
        except Exception:  # noqa: BLE001
            pass
        logger.info("CB %s: HALF_OPEN canary OK → CLOSED", target)
        return BreakerSnapshot(target, CircuitState.CLOSED, 0, None, 0)

    return _snapshot(target, state)


def get_snapshot(target: str) -> BreakerSnapshot:
    """Read current state without mutating anything."""
    return _snapshot(target, _read_state(target))


def get_all_snapshots(targets: list[str]) -> dict[str, dict]:
    """Convenience: snapshot dict for the /health and /metrics endpoints."""
    out: dict[str, dict] = {}
    for t in targets:
        snap = get_snapshot(t)
        trips = 0
        if redis_client:
            try:
                trips = int(redis_client.get(_trip_counter_key(t)) or 0)
            except Exception:  # noqa: BLE001
                trips = 0
        out[t] = {
            "state": snap.state.value,
            "failures_in_window": snap.failures_in_window,
            "cooldown_remaining_s": snap.cooldown_remaining_s,
            "opened_at_ms": snap.opened_at_ms,
            "total_trips": trips,
        }
    return out


def reset(target: str) -> None:
    """Test helper / admin: clear all CB state for a target."""
    if not redis_client:
        return
    try:
        redis_client.delete(
            _fails_key(target),
            _state_key(target),
            _opened_key(target),
            _trip_counter_key(target),
        )
    except Exception:  # noqa: BLE001
        pass
