"""Deterministic fake chat completion provider for testing and CI."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Literal

from mamagift_contracts.errors import WorkerError, WorkerErrorCode
from mamagift_contracts.llm import (
    CompletionRequest,
    CompletionResult,
    TokenUsage,
)


class FakeChatProvider:
    """Deterministic in-memory fake chat provider for unit/integration tests and CI.

    Supports:
    - Sequential canned responses via `responses` list or `add_response()`
    - Substring / keyword pattern matching via `canned_patterns` or `set_canned()`
    - Custom callback handler via `handler`
    - Default deterministic response generator based on request messages
    - Call tracking via `calls`
    """

    def __init__(
        self,
        *,
        model: str = "fake-qwen2.5-7b",
        provider_name: str = "fake_chat",
        responses: list[CompletionResult | str | Exception] | None = None,
        canned_patterns: dict[str, CompletionResult | str | Exception] | None = None,
        handler: Callable[[CompletionRequest], CompletionResult | str | Exception] | None = None,
    ) -> None:
        self.model = model
        self.provider_name = provider_name
        self.responses: list[CompletionResult | str | Exception] = list(responses or [])
        self.canned_patterns: dict[str, CompletionResult | str | Exception] = dict(
            canned_patterns or {}
        )
        self.handler = handler
        self.calls: list[CompletionRequest] = []

    def add_response(self, response: CompletionResult | str | Exception) -> None:
        """Add a canned response to the FIFO queue."""
        self.responses.append(response)

    def set_canned(self, pattern: str, response: CompletionResult | str | Exception) -> None:
        """Map a prompt substring/pattern to a canned response."""
        clean_pattern = pattern.strip() if pattern else ""
        if not clean_pattern:
            raise ValueError("pattern must be a non-empty string")
        self.canned_patterns[clean_pattern] = response

    def reset(self) -> None:
        """Clear call history and queued responses."""
        self.calls.clear()
        self.responses.clear()
        self.canned_patterns.clear()
        self.handler = None

    def _make_result(
        self,
        text: str,
        finish_reason: Literal["stop", "length", "content_filter", "error"] = "stop",
    ) -> CompletionResult:
        prompt_words = 10
        completion_words = len(text.split()) if text else 1
        return CompletionResult(
            text=text,
            model=self.model,
            provider=self.provider_name,
            finish_reason=finish_reason,
            usage=TokenUsage(
                prompt_tokens=prompt_words,
                completion_tokens=completion_words,
                total_tokens=prompt_words + completion_words,
            ),
        )

    def _resolve_item(self, item: CompletionResult | str | Exception) -> CompletionResult:
        if isinstance(item, Exception):
            raise item
        if isinstance(item, CompletionResult):
            return item
        if isinstance(item, str):
            return self._make_result(item)
        raise WorkerError(
            WorkerErrorCode.UPSTREAM_ERROR,
            f"Unsupported canned response type in fake chat provider: {type(item).__name__}",
            retryable=False,
        )

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        """Return a deterministic completion or queued canned response."""
        self.calls.append(request)

        # 1. Check sequential queue
        if self.responses:
            item = self.responses.pop(0)
            return self._resolve_item(item)

        # 2. Check pattern matching on message contents
        combined_text = " ".join(m.content for m in request.messages)
        for pattern, canned in self.canned_patterns.items():
            if pattern in combined_text:
                return self._resolve_item(canned)

        # 3. Check custom callback handler
        if self.handler is not None:
            handled = self.handler(request)
            return self._resolve_item(handled)

        # 4. Default deterministic generation
        last_user_msg = next(
            (m.content for m in reversed(request.messages) if m.role == "user"), ""
        )
        if request.response_format == "json_object":
            content = json.dumps({"answer": f"Fake answer for: {last_user_msg}"})
        else:
            content = f"Fake answer for: {last_user_msg}"

        return self._make_result(content)
