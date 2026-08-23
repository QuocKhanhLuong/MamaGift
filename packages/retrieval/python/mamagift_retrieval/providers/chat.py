"""Protocol definition for chat completion providers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from mamagift_contracts.llm import CompletionRequest, CompletionResult


@runtime_checkable
class ChatCompletionProvider(Protocol):
    """Protocol for LLM chat completion providers."""

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        """Execute a chat completion request and return the typed result."""
        ...
