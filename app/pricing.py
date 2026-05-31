"""Cost math for Claude API calls.

Pricing table lives in config.py — this module just does arithmetic.
"""

from __future__ import annotations

from app.config import DEFAULT_PRICING, MODEL_PRICING


def estimate_cost(input_tokens: int, output_tokens: int, model: str) -> dict:
    """Return a cost breakdown for a single request.

    Uses MODEL_PRICING when known, falls back to Sonnet rates so we never
    under-report. All figures USD.
    """
    rates = MODEL_PRICING.get(model, DEFAULT_PRICING)
    input_cost = (input_tokens / 1_000_000) * rates.input_per_million
    output_cost = (output_tokens / 1_000_000) * rates.output_per_million
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_cost": round(input_cost, 6),
        "output_cost": round(output_cost, 6),
        "total_cost": round(input_cost + output_cost, 6),
        "model": model,
    }
