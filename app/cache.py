"""Deterministic SHA256 prompt cache.

Cache key = SHA256(model | temperature | max_tokens | messages_json).
Reasons for hashing the full request shape:
  - same prompt at temperature=0 vs temperature=1 should NOT share a cache entry
  - same prompt to Haiku vs Sonnet should NOT share a cache entry
  - max_tokens influences truncation, so include it

Two Redis counters track hit/miss totals for /metrics:
  cache:hits     INCR on cache hit
  cache:misses   INCR on cache miss

Both are plain INCR — O(1) reads for the metrics endpoint.
"""

from __future__ import annotations

import hashlib
import json
from typing import Optional

from app.config import CACHE_ENABLED, CACHE_TTL_SECONDS
from app.deps import logger, redis_client
from app.models import Message

_CACHE_PREFIX = "cache:resp:"
_HITS_KEY = "cache:hits"
_MISSES_KEY = "cache:misses"


def _normalize_messages(messages: list[Message]) -> list[dict]:
    """Canonical JSON-able representation of messages.

    Keep this deterministic — anything non-deterministic (e.g. dict ordering)
    would shatter cache hits.
    """
    return [{"role": m.role, "content": m.content} for m in messages]


def compute_cache_key(
    model: str,
    temperature: float,
    max_tokens: int,
    messages: list[Message],
) -> str:
    """Compute the SHA256 cache key for a request.

    Returns the hex digest (no prefix). Callers prepend the namespace.
    """
    payload = {
        "model": model,
        "temperature": round(float(temperature), 4),  # avoid float jitter
        "max_tokens": int(max_tokens),
        "messages": _normalize_messages(messages),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def get_cached_response(cache_key: str) -> Optional[dict]:
    """Return cached response dict, or None on miss / cache disabled / no Redis."""
    if not CACHE_ENABLED or not redis_client:
        return None
    try:
        raw = redis_client.get(_CACHE_PREFIX + cache_key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache GET failed (%s); treating as miss", exc)
        return None

    if raw is None:
        try:
            redis_client.incr(_MISSES_KEY)
        except Exception:  # noqa: BLE001
            pass
        return None

    try:
        cached = json.loads(raw)
        redis_client.incr(_HITS_KEY)
        return cached
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache decode failed (%s); treating as miss", exc)
        return None


def set_cached_response(cache_key: str, response: dict) -> None:
    """Store a response under the given cache key with the configured TTL."""
    if not CACHE_ENABLED or not redis_client:
        return
    try:
        redis_client.setex(
            _CACHE_PREFIX + cache_key,
            CACHE_TTL_SECONDS,
            json.dumps(response, separators=(",", ":")),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Cache SETEX failed (%s); continuing without cache write", exc)


def get_cache_stats() -> dict:
    """Return current hit/miss counts and hit rate."""
    if not redis_client:
        return {"hits": 0, "misses": 0, "hit_rate": 0.0, "enabled": CACHE_ENABLED}
    try:
        hits = int(redis_client.get(_HITS_KEY) or 0)
        misses = int(redis_client.get(_MISSES_KEY) or 0)
    except Exception:  # noqa: BLE001
        hits, misses = 0, 0
    total = hits + misses
    return {
        "hits": hits,
        "misses": misses,
        "hit_rate": round(hits / total, 4) if total else 0.0,
        "enabled": CACHE_ENABLED,
    }
