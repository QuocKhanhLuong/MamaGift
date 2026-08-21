"""Typed contracts for LLM chat completion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str


class CompletionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage]
    max_output_tokens: int
    temperature: float = 0.0
    stop: list[str] = Field(default_factory=list)
    response_format: Literal["text", "json_object"] = "text"


class TokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class CompletionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    model: str
    provider: str
    finish_reason: Literal["stop", "length", "content_filter", "error"]
    usage: TokenUsage
