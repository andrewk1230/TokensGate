"""Sliding-window rate limiter using a Redis ZSET log.

Phase 2 shipped a fixed-window counter (INCR + EXPIRE per calendar minute).
That implementation had a known weakness, documented in its own comment:
boundary bursts and slow drips could escape the limit. We empirically
confirmed the slow-drip bypass by running 105 sequential cache-miss requests
at ~1.7s each — the limiter never triggered because each calendar minute
saw only ~35 of them.

This module is the Phase 2.5 fix: a true sliding-window log.

DESIGN
======

For each client we keep ONE Redis ZSET:

    rl:reqs:{client}
      score  = request timestamp in milliseconds
      member = "{uuid}:{token_count}"

On every request:
  1. ZREMRANGEBYSCORE drops members older than (now - 60s)
  2. ZCARD + ZRANGEBYSCORE read the current window's request count and token sum
  3. If adding this request would exceed either limit -> 429 (no write)
  4. Otherwise ZADD the new member; EXPIRE the key (defensive cleanup)

The token count is encoded in the ZSET member string so a single key holds
both axes of accounting. Parsing is O(N) where N is bounded by the request
limit (~100), so the math is fine.

TRADE-OFFS
==========

vs. fixed-window:
  + No boundary bursts; no slow-drip bypass
  + Window slides with the clock, not the calendar
  - O(N) token sum per request (still ~microseconds at our limits)
  - Slightly more memory per client (~4 KB at saturation)

vs. true token bucket (Lua):
  - Doesn't continuously replenish tokens; counts what was used in window
  + No Lua scripts -> simpler ops + easier debugging via redis-cli
  + Easier to introspect (just ZRANGE the key)

TESTABILITY
===========

`_now_ms()` is the only entry point that touches the clock. Tests can
monkeypatch it to advance a virtual time without sleeping.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import List, Optional

from fastapi import Request

from app.config import (
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_REQUESTS_PER_MIN,
    RATE_LIMIT_TOKENS_PER_MIN,
)
from app.deps import logger, redis_client

_WINDOW_MS = 60_000  # 60-second sliding window
_KEY_PREFIX = "rl:reqs:"
# Key TTL is 2x the window so an idle client's bucket auto-cleans.
_KEY_TTL_SECONDS = (_WINDOW_MS // 1000) * 2


@dataclass
class RateLimitDecision:
    allowed: bool
    reason: Optional[str]  # "requests" | "tokens" | None
    retry_after_seconds: int
    request_count: int
    token_count: int
    limit_requests: int
    limit_tokens: int


def _now_ms() -> int:
    """Single point of truth for time. Tests monkeypatch this."""
    return int(time.time() * 1000)


def client_id_from_request(request: Request) -> str:
    """Identify the client for bucketing.

    Priority: X-Client-ID header, then Authorization (Bearer XXX), then IP.
    """
    cid = request.headers.get("X-Client-ID")
    if cid:
        return f"id:{cid.strip()}"

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth.split(" ", 1)[1].strip()
        if token:
            return f"tok:{token[:16]}"

    if request.client and request.client.host:
        return f"ip:{request.client.host}"
    return "ip:unknown"


def _sum_tokens(members: List[str]) -> int:
    """Sum the token-count suffix off each ZSET member.

    Member format: "{uuid}:{tokens}". We split on the last ':' so future
    format additions to the front don't break parsing.
    """
    total = 0
    for m in members:
        try:
            total += int(m.rsplit(":", 1)[1])
        except (ValueError, IndexError):
            # Malformed member - ignore rather than crash the limiter
            continue
    return total


def _retry_after_seconds(key: str, now_ms: int) -> int:
    """Seconds until the oldest in-window request expires.

    If we can't read the ZSET (or it's empty), fall back to the full window.
    """
    if not redis_client:
        return _WINDOW_MS // 1000
    try:
        oldest = redis_client.zrange(key, 0, 0, withscores=True)
    except Exception:  # noqa: BLE001
        return _WINDOW_MS // 1000
    if not oldest:
        return _WINDOW_MS // 1000
    oldest_ms = int(oldest[0][1])
    remaining_ms = (oldest_ms + _WINDOW_MS) - now_ms
    return max(1, remaining_ms // 1000)


def check_and_increment(client: str, estimated_tokens: int) -> RateLimitDecision:
    """Read the current window state, decide, and (if allowed) record the request.

    Rejected requests do NOT count against the bucket — they're not added.
    This is a deliberate choice: it means a client hammering an already-full
    bucket gets predictable backoff signals instead of an ever-growing penalty.
    """
    if not RATE_LIMIT_ENABLED or not redis_client:
        return RateLimitDecision(
            allowed=True,
            reason=None,
            retry_after_seconds=0,
            request_count=0,
            token_count=0,
            limit_requests=RATE_LIMIT_REQUESTS_PER_MIN,
            limit_tokens=RATE_LIMIT_TOKENS_PER_MIN,
        )

    now_ms = _now_ms()
    window_start_ms = now_ms - _WINDOW_MS
    key = f"{_KEY_PREFIX}{client}"
    tokens = max(0, int(estimated_tokens))

    # --- Read current window state ---
    try:
        pipe = redis_client.pipeline()
        pipe.zremrangebyscore(key, 0, window_start_ms)
        pipe.zcard(key)
        # Inclusive range of in-window members; '+inf' covers any future-dated entries.
        pipe.zrangebyscore(key, window_start_ms, "+inf")
        _, current_count, members = pipe.execute()
        current_tokens = _sum_tokens(members if isinstance(members, list) else list(members))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Rate limiter Redis read error (%s); fail-open", exc)
        return RateLimitDecision(
            allowed=True,
            reason=None,
            retry_after_seconds=0,
            request_count=0,
            token_count=0,
            limit_requests=RATE_LIMIT_REQUESTS_PER_MIN,
            limit_tokens=RATE_LIMIT_TOKENS_PER_MIN,
        )

    # --- Decide ---
    projected_count = int(current_count) + 1
    projected_tokens = current_tokens + tokens

    if projected_count > RATE_LIMIT_REQUESTS_PER_MIN:
        return RateLimitDecision(
            allowed=False,
            reason="requests",
            retry_after_seconds=_retry_after_seconds(key, now_ms),
            request_count=int(current_count),
            token_count=current_tokens,
            limit_requests=RATE_LIMIT_REQUESTS_PER_MIN,
            limit_tokens=RATE_LIMIT_TOKENS_PER_MIN,
        )
    if projected_tokens > RATE_LIMIT_TOKENS_PER_MIN:
        return RateLimitDecision(
            allowed=False,
            reason="tokens",
            retry_after_seconds=_retry_after_seconds(key, now_ms),
            request_count=int(current_count),
            token_count=current_tokens,
            limit_requests=RATE_LIMIT_REQUESTS_PER_MIN,
            limit_tokens=RATE_LIMIT_TOKENS_PER_MIN,
        )

    # --- Record the allowed request ---
    member = f"{uuid.uuid4().hex}:{tokens}"
    try:
        pipe = redis_client.pipeline()
        pipe.zadd(key, {member: now_ms})
        pipe.expire(key, _KEY_TTL_SECONDS)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001
        # The decision is already 'allow'; if Redis hiccups on write, the
        # request still proceeds. Next request's read will reflect reality.
        logger.warning("Rate limiter ZADD error (%s); allowing without recording", exc)

    return RateLimitDecision(
        allowed=True,
        reason=None,
        retry_after_seconds=0,
        request_count=projected_count,
        token_count=projected_tokens,
        limit_requests=RATE_LIMIT_REQUESTS_PER_MIN,
        limit_tokens=RATE_LIMIT_TOKENS_PER_MIN,
    )
