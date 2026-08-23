"""OpenAI-compatible HTTP chat completion adapter."""

from __future__ import annotations

import asyncio
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

from mamagift_contracts.errors import (
    WorkerError,
    WorkerErrorCode,
)
from mamagift_contracts.llm import (
    CompletionRequest,
    CompletionResult,
    TokenUsage,
)

_LOCAL_RETRYABLE_BY_CODE: dict[WorkerErrorCode, bool] = {
    WorkerErrorCode.UNAUTHORIZED: False,
    WorkerErrorCode.BAD_REQUEST: False,
    WorkerErrorCode.TIMEOUT: True,
    WorkerErrorCode.UNAVAILABLE: True,
    WorkerErrorCode.MODEL_NOT_LOADED: True,
    WorkerErrorCode.UPSTREAM_ERROR: True,
}


class OpenAIMessagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = None
    content: str
    refusal: str | None = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, v: str) -> str:
        if not isinstance(v, str) or not v.strip():
            raise ValueError("message content must be a non-empty string")
        return v


class OpenAIChoicePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int | None = None
    message: OpenAIMessagePayload
    finish_reason: Literal["stop", "length", "content_filter", "error"]
    logprobs: Any | None = None


class OpenAIUsagePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    prompt_tokens_details: Any | None = None
    completion_tokens_details: Any | None = None


class OpenAIChatCompletionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    object: str | None = None
    created: int | None = None
    model: str | None = None
    choices: list[OpenAIChoicePayload] = Field(min_length=1)
    usage: OpenAIUsagePayload | None = None
    system_fingerprint: str | None = None
    service_tier: str | None = None


def _build_chat_endpoint(base_url: str) -> str:
    """Normalize base URL to point to /chat/completions endpoint."""
    url = base_url.rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return f"{url}/v1/chat/completions"


class OpenAICompatibleChatProvider:
    """Chat completion provider communicating with OpenAI-compatible endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 3,
        retry_backoff_seconds: float = 0.5,
        provider_name: str = "openai_compatible",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        clean_base = base_url.strip() if base_url else ""
        if not clean_base:
            raise ValueError("base_url must be a non-empty string")
        clean_model = model.strip() if model else ""
        if not clean_model:
            raise ValueError("model must be a non-empty string")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")

        self.base_url = clean_base.rstrip("/")
        self.model = clean_model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self.provider_name = provider_name
        self._endpoint_url = _build_chat_endpoint(self.base_url)
        self._http_client = http_client

    def _build_payload(self, request: CompletionRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_output_tokens,
            "temperature": request.temperature,
        }
        if request.stop:
            payload["stop"] = list(request.stop)
        if request.response_format == "json_object":
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _handle_error_response(self, response: httpx.Response) -> None:
        status = response.status_code
        text = response.text
        error_json: dict[str, Any] | None = None
        try:
            raw_json = response.json()
            if isinstance(raw_json, dict):
                error_json = raw_json
        except Exception:
            pass

        # Upstream might return a typed WorkerErrorResponse
        if error_json and "error" in error_json and isinstance(error_json["error"], dict):
            err_dict = error_json["error"]
            if "code" in err_dict and "message" in err_dict:
                raw_code = err_dict.get("code")
                code_enum: WorkerErrorCode | None = None
                if isinstance(raw_code, str):
                    try:
                        code_enum = WorkerErrorCode(raw_code)
                    except ValueError:
                        code_enum = None

                if code_enum is not None:
                    # Retryability is determined by our local policy.
                    # Upstream hint is advisory: it may narrow retrying, never widen it.
                    local_retryable = _LOCAL_RETRYABLE_BY_CODE.get(code_enum, False)
                    upstream_hint = err_dict.get("retryable")
                    if upstream_hint is not None:
                        retryable = local_retryable and bool(upstream_hint)
                    else:
                        retryable = local_retryable

                    details = err_dict.get("details", {})
                    if not isinstance(details, dict):
                        details = {}
                    raise WorkerError(
                        code=code_enum,
                        message=str(err_dict["message"]),
                        retryable=retryable,
                        status_code=status,
                        details=details,
                    )

        # Upstream OpenAI/Ollama error payload
        err_msg = ""
        if error_json and "error" in error_json:
            err_val = error_json["error"]
            if isinstance(err_val, dict):
                err_msg = str(err_val.get("message") or "")
            elif isinstance(err_val, str):
                err_msg = err_val
        elif error_json and "detail" in error_json:
            err_msg = str(error_json["detail"])

        if not err_msg:
            err_msg = text or f"HTTP {status}"

        if status in (401, 403):
            raise WorkerError(
                WorkerErrorCode.UNAUTHORIZED,
                f"LLM endpoint authorization failed ({status}): {err_msg}",
                retryable=False,
                status_code=status,
            )
        if status in (400, 422):
            raise WorkerError(
                WorkerErrorCode.BAD_REQUEST,
                f"LLM endpoint bad request ({status}): {err_msg}",
                retryable=False,
                status_code=status,
            )
        if status == 404:
            if "model" in err_msg.lower():
                raise WorkerError(
                    WorkerErrorCode.MODEL_NOT_LOADED,
                    f"LLM model not loaded ({status}): {err_msg}",
                    retryable=True,
                    status_code=404,
                )
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"LLM endpoint not found ({status}): {err_msg}",
                retryable=False,
                status_code=404,
            )
        if status in (408, 504):
            raise WorkerError(
                WorkerErrorCode.TIMEOUT,
                f"LLM endpoint timed out ({status}): {err_msg}",
                retryable=True,
                status_code=status,
            )
        if status in (429, 503):
            raise WorkerError(
                WorkerErrorCode.UNAVAILABLE,
                f"LLM endpoint unavailable ({status}): {err_msg}",
                retryable=True,
                status_code=status,
            )
        raise WorkerError(
            WorkerErrorCode.UPSTREAM_ERROR,
            f"LLM upstream error ({status}): {err_msg}",
            retryable=True,
            status_code=status,
        )

    def _parse_success_response(self, response: httpx.Response) -> CompletionResult:
        try:
            data = response.json()
        except Exception as exc:
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Failed to decode LLM response as JSON: {exc}. Body: {response.text[:200]}",
                retryable=True,
                status_code=502,
            ) from exc

        if not isinstance(data, dict):
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Invalid LLM response: root must be a JSON object, got {type(data).__name__}",
                retryable=True,
                status_code=502,
            )

        try:
            parsed = OpenAIChatCompletionResponse.model_validate(data)
        except Exception as exc:
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"Invalid LLM response payload: {exc}",
                retryable=True,
                status_code=502,
            ) from exc

        first_choice = parsed.choices[0]
        parsed_usage = parsed.usage
        if parsed_usage is not None:
            prompt_tokens = parsed_usage.prompt_tokens
            completion_tokens = parsed_usage.completion_tokens
            total_tokens = (
                parsed_usage.total_tokens
                if parsed_usage.total_tokens > 0
                else (prompt_tokens + completion_tokens)
            )
        else:
            prompt_tokens = 0
            completion_tokens = 0
            total_tokens = 0

        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        model_name = parsed.model or self.model

        return CompletionResult(
            text=first_choice.message.content,
            model=model_name,
            provider=self.provider_name,
            finish_reason=first_choice.finish_reason,
            usage=usage,
        )

    async def _send_request(
        self,
        client: httpx.AsyncClient,
        payload: dict[str, Any],
        headers: dict[str, str],
    ) -> CompletionResult:
        try:
            response = await client.post(
                self._endpoint_url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise WorkerError(
                WorkerErrorCode.TIMEOUT,
                f"Request to LLM endpoint timed out after {self.timeout_seconds}s: {exc}",
                retryable=True,
                status_code=504,
            ) from exc
        except (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise WorkerError(
                WorkerErrorCode.UNAVAILABLE,
                f"Network error connecting to LLM endpoint: {exc}",
                retryable=True,
                status_code=503,
            ) from exc
        except httpx.HTTPError as exc:
            raise WorkerError(
                WorkerErrorCode.UPSTREAM_ERROR,
                f"HTTP error connecting to LLM endpoint: {exc}",
                retryable=True,
                status_code=502,
            ) from exc

        if response.is_error:
            self._handle_error_response(response)

        return self._parse_success_response(response)

    async def complete(self, request: CompletionRequest) -> CompletionResult:
        """Execute chat completion with bounded retries on retryable errors."""
        max_attempts = max(1, self.max_retries + 1)
        last_error: WorkerError | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                if self._http_client is not None:
                    return await self._send_request(
                        self._http_client,
                        self._build_payload(request),
                        self._build_headers(),
                    )

                timeout = httpx.Timeout(self.timeout_seconds)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    return await self._send_request(
                        client,
                        self._build_payload(request),
                        self._build_headers(),
                    )
            except WorkerError as exc:
                last_error = exc
                if not exc.retryable or attempt >= max_attempts:
                    raise exc

                delay = self.retry_backoff_seconds * (2 ** (attempt - 1))
                if delay > 0:
                    await asyncio.sleep(delay)
            except Exception as exc:
                wrapped = WorkerError(
                    WorkerErrorCode.UPSTREAM_ERROR,
                    f"Unexpected error executing LLM completion: {exc}",
                    retryable=False,
                )
                raise wrapped from exc

        if last_error is not None:
            raise last_error
        raise WorkerError(
            WorkerErrorCode.UPSTREAM_ERROR,
            "Completion failed with no result",
            retryable=False,
        )
