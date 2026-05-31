"""Cost-aware routing.

Header `X-Route-Strategy` controls behavior:
  - "auto"        (default): use ROUTER_THRESHOLD_TOKENS to pick cheap vs expensive
  - "cheap"       : force CHEAP_MODEL
  - "expensive"   : force EXPENSIVE_MODEL
  - "explicit"    : trust the model field in the request body unchanged

If the request body specifies a model AND strategy is "auto", the explicit
choice still wins — we never silently override an intentional model pick.
The router only fires when the client opts in (no model in body, or
strategy != "explicit").
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import Request

from app.config import CHEAP_MODEL, EXPENSIVE_MODEL, ROUTER_THRESHOLD_TOKENS


@dataclass
class RoutingDecision:
    model: str
    strategy: str
    reason: str
    threshold: int
    estimated_input_tokens: int


def _strategy_from_request(request: Optional[Request], body_model: Optional[str]) -> str:
    if request is not None:
        header = request.headers.get("X-Route-Strategy", "").strip().lower()
        if header in {"auto", "cheap", "expensive", "explicit"}:
            return header
    # Default: if user passed a real model name, respect it; else auto.
    if body_model and body_model.lower() != "auto":
        return "explicit"
    return "auto"


def choose_model(
    request: Optional[Request],
    body_model: Optional[str],
    estimated_input_tokens: int,
) -> RoutingDecision:
    """Pick the upstream model for this request."""
    strategy = _strategy_from_request(request, body_model)

    if strategy == "explicit" and body_model:
        return RoutingDecision(
            model=body_model,
            strategy="explicit",
            reason="client specified model in body",
            threshold=ROUTER_THRESHOLD_TOKENS,
            estimated_input_tokens=estimated_input_tokens,
        )

    # Explicit was requested via header but no model in body — fall back to
    # auto sizing, but label the decision so the response makes the fallback
    # visible to the caller (instead of silently pretending the request was "auto").
    explicit_fallback = strategy == "explicit" and not body_model

    if strategy == "cheap":
        return RoutingDecision(
            model=CHEAP_MODEL,
            strategy="cheap",
            reason="forced cheap via header",
            threshold=ROUTER_THRESHOLD_TOKENS,
            estimated_input_tokens=estimated_input_tokens,
        )

    if strategy == "expensive":
        return RoutingDecision(
            model=EXPENSIVE_MODEL,
            strategy="expensive",
            reason="forced expensive via header",
            threshold=ROUTER_THRESHOLD_TOKENS,
            estimated_input_tokens=estimated_input_tokens,
        )

    # auto (or auto_fallback when explicit was requested without a body model)
    label = "auto_fallback" if explicit_fallback else "auto"
    reason_prefix = (
        "explicit strategy requested but no model in body; "
        if explicit_fallback else ""
    )
    if estimated_input_tokens < ROUTER_THRESHOLD_TOKENS:
        return RoutingDecision(
            model=CHEAP_MODEL,
            strategy=label,
            reason=f"{reason_prefix}estimated {estimated_input_tokens} < {ROUTER_THRESHOLD_TOKENS}",
            threshold=ROUTER_THRESHOLD_TOKENS,
            estimated_input_tokens=estimated_input_tokens,
        )
    return RoutingDecision(
        model=EXPENSIVE_MODEL,
        strategy=label,
        reason=f"{reason_prefix}estimated {estimated_input_tokens} >= {ROUTER_THRESHOLD_TOKENS}",
        threshold=ROUTER_THRESHOLD_TOKENS,
        estimated_input_tokens=estimated_input_tokens,
    )
