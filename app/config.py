"""Centralized configuration: env vars, model pricing, defaults.

Everything tunable lives here. Other modules import from here so we have
exactly one place to change pricing, limits, and model identifiers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


# ----------------------------------------------------------------------------
# Environment
# ----------------------------------------------------------------------------

CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")


# ----------------------------------------------------------------------------
# Cache configuration
# ----------------------------------------------------------------------------

CACHE_TTL_SECONDS: int = int(os.getenv("CACHE_TTL_SECONDS", "86400"))  # 24h
CACHE_ENABLED: bool = os.getenv("CACHE_ENABLED", "true").lower() == "true"


# ----------------------------------------------------------------------------
# Rate limit configuration
# ----------------------------------------------------------------------------

RATE_LIMIT_ENABLED: bool = os.getenv("RATE_LIMIT_ENABLED", "true").lower() == "true"
RATE_LIMIT_REQUESTS_PER_MIN: int = int(os.getenv("RATE_LIMIT_REQUESTS_PER_MIN", "100"))
RATE_LIMIT_TOKENS_PER_MIN: int = int(os.getenv("RATE_LIMIT_TOKENS_PER_MIN", "100000"))


# ----------------------------------------------------------------------------
# Routing configuration
# ----------------------------------------------------------------------------

ROUTER_THRESHOLD_TOKENS: int = int(os.getenv("ROUTER_THRESHOLD_TOKENS", "500"))
CHEAP_MODEL: str = os.getenv("CHEAP_MODEL", "claude-haiku-4-5-20251001")
EXPENSIVE_MODEL: str = os.getenv("EXPENSIVE_MODEL", "claude-sonnet-4-5-20250929")


# ----------------------------------------------------------------------------
# Phase 3: Circuit breaker
# Rolling-window failure tracker. Trips OPEN if CB_FAILURE_THRESHOLD failures
# accumulate within CB_WINDOW_SECONDS. Stays OPEN for CB_COOLDOWN_SECONDS,
# then enters HALF_OPEN: the next request becomes a canary. Canary success
# closes the circuit; canary failure re-opens it with a fresh cooldown.
# ----------------------------------------------------------------------------

CIRCUIT_BREAKER_ENABLED: bool = os.getenv("CIRCUIT_BREAKER_ENABLED", "true").lower() == "true"
CB_FAILURE_THRESHOLD: int = int(os.getenv("CB_FAILURE_THRESHOLD", "5"))
CB_WINDOW_SECONDS: int = int(os.getenv("CB_WINDOW_SECONDS", "30"))
CB_COOLDOWN_SECONDS: int = int(os.getenv("CB_COOLDOWN_SECONDS", "60"))


# ----------------------------------------------------------------------------
# Phase 3: Ollama fallback provider
# When the Anthropic circuit is OPEN or a retryable error fires, the gateway
# falls back to a local Ollama model. Ollama must be reachable at OLLAMA_BASE_URL
# (default points at the host machine from inside Docker).
# ----------------------------------------------------------------------------

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.2:1b")
OLLAMA_TIMEOUT_SECONDS: int = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))
OLLAMA_FALLBACK_ENABLED: bool = os.getenv("OLLAMA_FALLBACK_ENABLED", "true").lower() == "true"


# ----------------------------------------------------------------------------
# Claude pricing table (USD per 1M tokens)
# Source: https://www.anthropic.com/pricing
# ----------------------------------------------------------------------------

@dataclass(frozen=True)
class ModelPricing:
    input_per_million: float
    output_per_million: float


MODEL_PRICING: dict[str, ModelPricing] = {
    # --- Current generation (Claude 4.x) ---
    # NOTE: verify these against anthropic.com/pricing before quoting on a resume.
    # Pricing as of last check; safe estimates aligned with prior Haiku/Sonnet/Opus tiers.
    "claude-haiku-4-5-20251001": ModelPricing(1.00, 5.00),
    "claude-sonnet-4-5-20250929": ModelPricing(3.00, 15.00),
    "claude-sonnet-4-6": ModelPricing(3.00, 15.00),
    "claude-opus-4-1-20250805": ModelPricing(15.00, 75.00),
    "claude-opus-4-5-20251101": ModelPricing(15.00, 75.00),
    "claude-opus-4-6": ModelPricing(15.00, 75.00),
    "claude-opus-4-7": ModelPricing(15.00, 75.00),

    # --- Legacy (kept for backwards compatibility; mostly 404 now) ---
    "claude-3-haiku-20240307": ModelPricing(0.25, 1.25),
    "claude-3-5-haiku-20241022": ModelPricing(1.00, 5.00),
    "claude-3-sonnet-20240229": ModelPricing(3.00, 15.00),
    "claude-3-5-sonnet-20241022": ModelPricing(3.00, 15.00),
    "claude-3-opus-20240229": ModelPricing(15.00, 75.00),
}

# Fallback when a model isn't in the table — assume Sonnet rates so we
# never under-report cost.
DEFAULT_PRICING: ModelPricing = MODEL_PRICING["claude-sonnet-4-5-20250929"]
