"""Pydantic request/response models (OpenAI-compatible shape)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Message(BaseModel):
    """Single message in a conversation."""

    role: str = Field(..., description="'system', 'user', or 'assistant'")
    content: str = Field(..., description="Message content")


class ChatCompletionRequest(BaseModel):
    """OpenAI-compatible chat completion request."""

    model: Optional[str] = Field(
        default=None,
        description="Model identifier. If None or 'auto', router chooses based on size.",
    )
    messages: List[Message] = Field(..., min_length=1)
    max_tokens: Optional[int] = Field(default=1024, ge=1, le=8192)
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
