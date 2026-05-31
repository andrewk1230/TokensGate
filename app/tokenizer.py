"""Token counting helpers.

IMPORTANT: tiktoken is OpenAI's BPE — Claude uses a different tokenizer.
We use tiktoken ONLY for pre-call estimates (routing, rate-limit accounting
before we hit Claude). For real billing math, use `response.usage.input_tokens`
and `response.usage.output_tokens` returned by the Anthropic SDK.

Empirically tiktoken is within ~10-20% of Claude's tokenizer for English prose,
which is good enough to make routing decisions but NOT good enough for cost
reporting on a resume.
"""

from __future__ import annotations

from app.deps import logger, tokenizer
from app.models import Message


def estimate_tokens(text: str) -> int:
    """Estimate tokens via tiktoken. Falls back to whitespace split.

    This is an ESTIMATE only — see module docstring.
    """
    if not tokenizer:
        return max(1, len(text.split()))
    try:
        return len(tokenizer.encode(text))
    except Exception as exc:  # noqa: BLE001
        logger.warning("tiktoken encode failed (%s); using whitespace estimate", exc)
        return max(1, len(text.split()))


def estimate_messages_tokens(messages: list[Message]) -> int:
    """Estimate total tokens for a list of messages.

    Adds ~4 tokens of overhead per message to roughly account for role/format
    framing — matches OpenAI's published heuristic. Not exact for Claude but
    close enough for routing decisions.
    """
    if not messages:
        return 0
    body = sum(estimate_tokens(m.content) for m in messages)
    return body + 4 * len(messages)
