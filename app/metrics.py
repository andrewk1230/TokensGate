"""Metrics: counter-based aggregates + recent-request log.

We do NOT use `KEYS metrics:*` for aggregation anymore — that's O(n) and
blocks Redis. Instead:

  metrics:totals:requests          INCR per request
  metrics:totals:errors            INCR on error
  metrics:totals:input_tokens      INCRBY input_tokens
  metrics:totals:output_tokens     INCRBY output_tokens
  metrics:totals:cost_micros       INCRBY round(total_cost * 1e6)
  metrics:totals:response_time_ms  INCRBY response_time_ms

  metrics:recent                   LPUSH JSON record, LTRIM to 200

`cost_micros` is integer (USD * 1e6) so Redis INCRBY works — Redis doesn't
have an atomic float INCR. We divide by 1e6 on read.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from app.cache import get_cache_stats
from app.deps import logger, redis_client
from app.pricing import estimate_cost

_RECENT_KEY = "metrics:recent"
_RECENT_MAX = 200


def log_request_metrics(
    *,
    request_id: str,
    client: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    response_time_ms: float,
    cache_hit: bool,
    routing_strategy: str,
    status: str = "success",
    error: Optional[str] = None,
) -> None:
    """Update Redis aggregates and append to the recent-requests list."""
    cost = estimate_cost(input_tokens, output_tokens, model)
    record = {
        "request_id": request_id,
        "client": client,
        "timestamp": datetime.utcnow().isoformat(),
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "response_time_ms": round(response_time_ms, 2),
        "cache_hit": cache_hit,
        "routing_strategy": routing_strategy,
        "status": status,
        "error": error,
        "cost": cost,
    }

    logger.info(
        "req=%s client=%s model=%s in=%d out=%d %.0fms cache=%s strat=%s status=%s cost=$%.6f",
        request_id, client, model, input_tokens, output_tokens,
        response_time_ms, cache_hit, routing_strategy, status, cost["total_cost"],
    )

    if not redis_client:
        return

    try:
        pipe = redis_client.pipeline()
        pipe.incr("metrics:totals:requests")
        if status != "success":
            pipe.incr("metrics:totals:errors")
        pipe.incrby("metrics:totals:input_tokens", int(input_tokens))
        pipe.incrby("metrics:totals:output_tokens", int(output_tokens))
        pipe.incrby("metrics:totals:cost_micros", int(round(cost["total_cost"] * 1_000_000)))
        pipe.incrby("metrics:totals:response_time_ms", int(round(response_time_ms)))
        pipe.lpush(_RECENT_KEY, json.dumps(record, separators=(",", ":")))
        pipe.ltrim(_RECENT_KEY, 0, _RECENT_MAX - 1)
        pipe.execute()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to log metrics to Redis: %s", exc)


def get_aggregate_metrics() -> dict:
    """Read O(1) aggregates from Redis. Safe for production."""
    if not redis_client:
        return {
            "total_requests": 0,
            "total_errors": 0,
            "total_input_tokens": 0,
            "total_output_tokens": 0,
            "total_cost": 0.0,
            "average_response_time_ms": 0.0,
            "cache": get_cache_stats(),
        }
    try:
        keys = [
            "metrics:totals:requests",
            "metrics:totals:errors",
            "metrics:totals:input_tokens",
            "metrics:totals:output_tokens",
            "metrics:totals:cost_micros",
            "metrics:totals:response_time_ms",
        ]
        raw = redis_client.mget(keys)
        reqs = int(raw[0] or 0)
        errs = int(raw[1] or 0)
        in_tok = int(raw[2] or 0)
        out_tok = int(raw[3] or 0)
        cost_micros = int(raw[4] or 0)
        rt_ms = int(raw[5] or 0)
    except Exception as exc:  # noqa: BLE001
        logger.warning("metrics read failed: %s", exc)
        reqs = errs = in_tok = out_tok = cost_micros = rt_ms = 0

    avg_rt = (rt_ms / reqs) if reqs else 0.0
    return {
        "total_requests": reqs,
        "total_errors": errs,
        "total_input_tokens": in_tok,
        "total_output_tokens": out_tok,
        "total_cost": round(cost_micros / 1_000_000, 6),
        "average_response_time_ms": round(avg_rt, 2),
        "cache": get_cache_stats(),
    }


def get_recent_requests(limit: int = 20) -> list[dict]:
    """Return the most recent N requests for debugging.

    Guard against limit <= 0 explicitly: `lrange(0, -1)` would otherwise return
    the entire list because Redis treats -1 as "last element".
    """
    if not redis_client or limit <= 0:
        return []
    effective = min(limit, _RECENT_MAX)
    try:
        raw = redis_client.lrange(_RECENT_KEY, 0, effective - 1)
        return [json.loads(r) for r in raw]
    except Exception as exc:  # noqa: BLE001
        logger.warning("recent metrics read failed: %s", exc)
        return []


def reset_metrics() -> None:
    """Test helper: nuke all metrics counters. Not exposed via HTTP."""
    if not redis_client:
        return
    try:
        redis_client.delete(
            "metrics:totals:requests",
            "metrics:totals:errors",
            "metrics:totals:input_tokens",
            "metrics:totals:output_tokens",
            "metrics:totals:cost_micros",
            "metrics:totals:response_time_ms",
            _RECENT_KEY,
            "cache:hits",
            "cache:misses",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("reset_metrics failed: %s", exc)
