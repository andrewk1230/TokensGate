"""Singleton clients: Redis, Anthropic, tiktoken.

Initialized once at import time. If a client fails to come up, we log
and leave the singleton as None — callers must handle that gracefully
(this keeps /health honest about what's broken).
"""

from __future__ import annotations

import logging
from typing import Optional

import redis
import tiktoken
from anthropic import Anthropic

from app.config import CLAUDE_API_KEY, LOG_LEVEL, REDIS_URL

# ----------------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("tokensgate")


# ----------------------------------------------------------------------------
# Redis
# ----------------------------------------------------------------------------

redis_client: Optional[redis.Redis]
try:
    redis_client = redis.from_url(REDIS_URL, decode_responses=True)
    redis_client.ping()
    logger.info("Redis connection successful (%s)", REDIS_URL)
except Exception as exc:  # noqa: BLE001 - want broad catch at startup
    logger.error("Redis connection failed: %s", exc)
    redis_client = None


# ----------------------------------------------------------------------------
# Anthropic
# ----------------------------------------------------------------------------

anthropic_client: Optional[Anthropic]
try:
    anthropic_client = Anthropic(api_key=CLAUDE_API_KEY) if CLAUDE_API_KEY else None
    if anthropic_client:
        logger.info("Anthropic client initialized")
    else:
        logger.warning("CLAUDE_API_KEY not set; Anthropic client disabled")
except Exception as exc:  # noqa: BLE001
    logger.error("Anthropic client failed: %s", exc)
    anthropic_client = None


# ----------------------------------------------------------------------------
# tiktoken (estimation only — Claude uses a different tokenizer)
# ----------------------------------------------------------------------------

tokenizer: Optional[tiktoken.Encoding]
try:
    tokenizer = tiktoken.encoding_for_model("gpt-3.5-turbo")
    logger.info("tiktoken estimator initialized")
except Exception as exc:  # noqa: BLE001
    logger.error("tiktoken init failed: %s", exc)
    tokenizer = None
