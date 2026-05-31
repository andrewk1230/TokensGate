"""TokensGate entry point.

This module is intentionally thin. All routing logic lives in `app.api`,
all business logic in the rest of the `app/` package. Keeping this file
small means `uvicorn main:app` (and the Dockerfile CMD) keep working
without churn as the project grows.

Layers (matches Reviews/TokensGate-Execution-Plan):
  Layer 1  Ingestion & Optimization   app.tokenizer, app.cache
  Layer 2  Traffic & Rate Management  app.rate_limit, app.router
  Layer 3  Fault-Tolerant Egress      app.circuit_breaker, app.providers
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api import router as api_router
from app.config import (
    CB_COOLDOWN_SECONDS,
    CB_FAILURE_THRESHOLD,
    CB_WINDOW_SECONDS,
    CIRCUIT_BREAKER_ENABLED,
    ENVIRONMENT,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    REDIS_URL,
)
from app.deps import anthropic_client, logger, redis_client, tokenizer


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Replaces deprecated @on_event(startup/shutdown).

    Anything heavy (warm caches, prime connections) goes before `yield`.
    Cleanup runs after.
    """
    # --- startup ---
    logger.info("=" * 70)
    logger.info("TokensGate v%s starting up", __version__)
    logger.info("=" * 70)
    logger.info("Environment:     %s", ENVIRONMENT)
    logger.info("Redis URL:       %s", REDIS_URL)
    logger.info("Redis:           %s", "ready" if redis_client else "DISABLED")
    logger.info("Anthropic:       %s", "ready" if anthropic_client else "DISABLED")
    logger.info("tiktoken:        %s", "ready" if tokenizer else "DISABLED")
    logger.info("Circuit Breaker: %s (threshold=%d/%ds, cooldown=%ds)",
                "enabled" if CIRCUIT_BREAKER_ENABLED else "disabled",
                CB_FAILURE_THRESHOLD, CB_WINDOW_SECONDS, CB_COOLDOWN_SECONDS)
    logger.info("Ollama fallback: %s @ %s", OLLAMA_MODEL, OLLAMA_BASE_URL)
    logger.info("=" * 70)

    yield

    # --- shutdown ---
    logger.info("TokensGate shutting down")
    if redis_client:
        try:
            redis_client.close()
        except Exception:  # noqa: BLE001
            pass


app = FastAPI(
    title="TokensGate",
    description="Intelligent LLM API Gateway with Token Optimization & Fault Tolerance",
    version=__version__,
    lifespan=lifespan,
)

app.include_router(api_router)


if __name__ == "__main__":
    import uvicorn

    from app.config import LOG_LEVEL

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level=LOG_LEVEL.lower())
