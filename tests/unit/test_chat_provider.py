"""Unit tests for ChatCompletionProvider, OpenAICompatibleChatProvider, and FakeChatProvider."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from services.api.app.settings import Settings

from mamagift_contracts.errors import (
    WorkerError,
    WorkerErrorCode,
)
from mamagift_contracts.llm import (
    ChatMessage,
    CompletionRequest,
    CompletionResult,
    TokenUsage,
)
from mamagift_retrieval.providers import (
    ChatCompletionProvider,
    FakeChatProvider,
    OpenAICompatibleChatProvider,
)


def _create_sample_request(
    messages: list[ChatMessage] | None = None,
    response_format: str = "text",
    stop: list[str] | None = None,
) -> CompletionRequest:
    return CompletionRequest(
        messages=messages
        or [
            ChatMessage(role="system", content="You are a helpful assistant."),
            ChatMessage(role="user", content="What is the document number?"),
        ],
        max_output_tokens=256,
        temperature=0.0,
        stop=stop or [],
        response_format=response_format,  # type: ignore[arg-type]
    )


def _create_mock_response(
    status_code: int = 200,
    json_data: Any = None,
    text_data: str | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    if json_data is not None:
        content = json.dumps(json_data).encode("utf-8")
        resp_headers = {"content-type": "application/json"}
    elif text_data is not None:
        content = text_data.encode("utf-8")
        resp_headers = {"content-type": "text/plain"}
    else:
        content = b""
        resp_headers = {}
    if headers:
        resp_headers.update(headers)
    return httpx.Response(
        status_code=status_code,
        headers=resp_headers,
        content=content,
        request=httpx.Request("POST", "http://test/chat/completions"),
    )


@pytest.mark.unit
class TestChatProviderProtocols:
    """Verify that both providers conform to the ChatCompletionProvider Protocol."""

    def test_protocol_conformance(self) -> None:
        fake = FakeChatProvider()
        assert isinstance(fake, ChatCompletionProvider)

        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen2.5-7b-instruct",
        )
        assert isinstance(provider, ChatCompletionProvider)


@pytest.mark.unit
class TestOpenAICompatibleInitAndConfig:
    """Test constructor parameter validation and endpoint normalization."""

    def test_endpoint_normalization(self) -> None:
        cases = [
            ("http://localhost:8090", "http://localhost:8090/v1/chat/completions"),
            ("http://localhost:8090/", "http://localhost:8090/v1/chat/completions"),
            ("http://localhost:8090/v1", "http://localhost:8090/v1/chat/completions"),
            ("http://localhost:8090/v1/", "http://localhost:8090/v1/chat/completions"),
            (
                "http://localhost:8090/v1/chat/completions",
                "http://localhost:8090/v1/chat/completions",
            ),
            (
                "http://localhost:11434/v1",
                "http://localhost:11434/v1/chat/completions",
            ),
        ]
        for base_url, expected_endpoint in cases:
            provider = OpenAICompatibleChatProvider(base_url=base_url, model="test-model")
            assert provider._endpoint_url == expected_endpoint

    def test_invalid_init_arguments(self) -> None:
        with pytest.raises(ValueError, match="base_url"):
            OpenAICompatibleChatProvider(base_url="", model="test")
        with pytest.raises(ValueError, match="base_url"):
            OpenAICompatibleChatProvider(base_url="   ", model="test")
        with pytest.raises(ValueError, match="model"):
            OpenAICompatibleChatProvider(base_url="http://localhost:8090", model="")
        with pytest.raises(ValueError, match="model"):
            OpenAICompatibleChatProvider(base_url="http://localhost:8090", model="   ")
        with pytest.raises(ValueError, match="timeout_seconds"):
            OpenAICompatibleChatProvider(
                base_url="http://localhost:8090", model="test", timeout_seconds=0
            )
        with pytest.raises(ValueError, match="timeout_seconds"):
            OpenAICompatibleChatProvider(
                base_url="http://localhost:8090", model="test", timeout_seconds=-5
            )
        with pytest.raises(ValueError, match="max_retries"):
            OpenAICompatibleChatProvider(
                base_url="http://localhost:8090", model="test", max_retries=-1
            )
        with pytest.raises(ValueError, match="retry_backoff_seconds"):
            OpenAICompatibleChatProvider(
                base_url="http://localhost:8090", model="test", retry_backoff_seconds=-0.1
            )


@pytest.mark.unit
class TestOpenAICompatiblePayloadAndHeaders:
    """Test payload building and header serialization."""

    def test_build_payload_standard_text(self) -> None:
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen2.5-7b-instruct",
        )
        req = _create_sample_request(stop=["\n\n", "User:"])
        payload = provider._build_payload(req)

        assert payload["model"] == "qwen2.5-7b-instruct"
        assert payload["max_tokens"] == 256
        assert payload["temperature"] == 0.0
        assert payload["stop"] == ["\n\n", "User:"]
        assert len(payload["messages"]) == 2
        assert payload["messages"][0] == {
            "role": "system",
            "content": "You are a helpful assistant.",
        }
        assert payload["messages"][1] == {
            "role": "user",
            "content": "What is the document number?",
        }
        assert "response_format" not in payload

    def test_build_payload_json_object_format(self) -> None:
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen2.5-7b-instruct",
        )
        req = _create_sample_request(response_format="json_object")
        payload = provider._build_payload(req)
        assert payload["response_format"] == {"type": "json_object"}

    def test_build_headers_with_and_without_api_key(self) -> None:
        provider_no_key = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            api_key=None,
        )
        headers_no_key = provider_no_key._build_headers()
        assert "Authorization" not in headers_no_key
        assert headers_no_key["Content-Type"] == "application/json"
        assert headers_no_key["Accept"] == "application/json"

        provider_with_key = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            api_key="secret-token-123",
        )
        headers_with_key = provider_with_key._build_headers()
        assert headers_with_key["Authorization"] == "Bearer secret-token-123"


@pytest.mark.unit
class TestOpenAICompatibleResponseParsing:
    """Test successful and malformed response parsing."""

    def test_parse_valid_response(self) -> None:
        mock_data = {
            "id": "chatcmpl-test-1",
            "object": "chat.completion",
            "model": "qwen2.5-7b-instruct",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": "Số văn bản là 123/QĐ-UBND.",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 15,
                "completion_tokens": 8,
                "total_tokens": 23,
            },
        }

        transport = httpx.MockTransport(lambda req: _create_mock_response(json_data=mock_data))
        client = httpx.AsyncClient(transport=transport)

        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen2.5-7b-instruct",
            http_client=client,
        )

        req = _create_sample_request()
        result = asyncio.run(provider.complete(req))

        assert isinstance(result, CompletionResult)
        assert result.text == "Số văn bản là 123/QĐ-UBND."
        assert result.model == "qwen2.5-7b-instruct"
        assert result.provider == "openai_compatible"
        assert result.finish_reason == "stop"
        assert result.usage.prompt_tokens == 15
        assert result.usage.completion_tokens == 8
        assert result.usage.total_tokens == 23

    def test_parse_missing_usage_defaults_to_zero(self) -> None:
        mock_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Hello",
                    },
                    "finish_reason": "length",
                }
            ],
        }

        transport = httpx.MockTransport(lambda req: _create_mock_response(json_data=mock_data))
        client = httpx.AsyncClient(transport=transport)

        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="test-model",
            http_client=client,
        )
        result = asyncio.run(provider.complete(_create_sample_request()))
        assert result.finish_reason == "length"
        assert result.usage == TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0)

    def test_malformed_non_json_response_fails_loudly(self) -> None:
        transport = httpx.MockTransport(
            lambda req: _create_mock_response(text_data="<html>502 Bad Gateway</html>")
        )
        client = httpx.AsyncClient(transport=transport)
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="test-model",
            max_retries=0,
            http_client=client,
        )
        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))
        assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
        assert exc_info.value.status_code == 502

    @pytest.mark.parametrize(
        "invalid_json",
        [
            [],  # Array instead of object
            "string-response",  # String instead of object
            {},  # Missing choices
            {"choices": []},  # Empty choices
            {"choices": ["not-a-dict"]},  # Choice is not a dict
            {"choices": [{}]},  # Choice missing message
            {"choices": [{"message": "not-a-dict"}]},  # Message not a dict
            {"choices": [{"message": {}}]},  # Missing content
            {"choices": [{"message": {"content": None}}]},  # Content is None
            {"choices": [{"message": {"content": 12345}}]},  # Content is not string
            {"choices": [{"message": {"content": ""}, "finish_reason": "stop"}]},  # Empty content
            {
                "choices": [{"message": {"content": "   "}, "finish_reason": "stop"}]
            },  # Whitespace content
            {"choices": [{"message": {"content": "Valid answer"}}]},  # Missing finish_reason
            {
                "choices": [{"message": {"content": "Valid answer"}, "finish_reason": None}]
            },  # None finish_reason
            {
                "choices": [
                    {"message": {"content": "Valid answer"}, "finish_reason": "unknown_reason"}
                ]
            },  # Unknown finish_reason
            {
                "extra_field": "invalid",
                "choices": [{"message": {"content": "Valid"}, "finish_reason": "stop"}],
            },  # Extra root field
            {
                "choices": [
                    {"message": {"content": "Valid"}, "finish_reason": "stop", "extra_choice": 123}
                ]
            },  # Extra choice field
            {
                "choices": [
                    {"message": {"content": "Valid", "extra_msg": "no"}, "finish_reason": "stop"}
                ]
            },  # Extra message field
            {
                "choices": [{"message": {"content": "Valid"}, "finish_reason": "stop"}],
                "usage": {"extra_usage": 1},
            },  # Extra usage field
        ],
    )
    def test_malformed_json_structure_fails_loudly(self, invalid_json: Any) -> None:
        transport = httpx.MockTransport(lambda req: _create_mock_response(json_data=invalid_json))
        client = httpx.AsyncClient(transport=transport)
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="test-model",
            max_retries=0,
            http_client=client,
        )
        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))
        assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
        assert exc_info.value.status_code == 502

    def test_empty_content_in_successful_response_fails_loudly(self) -> None:
        mock_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "",
                    },
                    "finish_reason": "stop",
                }
            ]
        }
        transport = httpx.MockTransport(lambda req: _create_mock_response(json_data=mock_data))
        client = httpx.AsyncClient(transport=transport)
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="test-model",
            max_retries=0,
            http_client=client,
        )
        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))
        assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
        assert exc_info.value.status_code == 502

    def test_unknown_finish_reason_fails_loudly_without_coercion(self) -> None:
        mock_data = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Valid text",
                    },
                    "finish_reason": "invalid_custom_finish_reason",
                }
            ]
        }
        transport = httpx.MockTransport(lambda req: _create_mock_response(json_data=mock_data))
        client = httpx.AsyncClient(transport=transport)
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="test-model",
            max_retries=0,
            http_client=client,
        )
        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))
        assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
        assert exc_info.value.status_code == 502

    def test_unknown_extra_fields_fail_loudly(self) -> None:
        mock_data = {
            "id": "chatcmpl-123",
            "unexpected_top_key": "bad",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "Valid text",
                    },
                    "finish_reason": "stop",
                }
            ],
        }
        transport = httpx.MockTransport(lambda req: _create_mock_response(json_data=mock_data))
        client = httpx.AsyncClient(transport=transport)
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="test-model",
            max_retries=0,
            http_client=client,
        )
        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))
        assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
        assert exc_info.value.status_code == 502


@pytest.mark.unit
class TestOpenAICompatibleErrorMappingAndRetries:
    """Test error code mapping, non-retryable vs retryable errors, and bounded backoff."""

    def test_auth_rejection_401_surfaces_unauthorized_and_no_retry(self) -> None:
        attempt_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            return _create_mock_response(
                status_code=401,
                json_data={"error": {"message": "Invalid API key"}},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="test-model",
            max_retries=3,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.UNAUTHORIZED
        assert exc_info.value.retryable is False
        assert exc_info.value.status_code == 401
        assert attempt_count == 1  # Crucial: non-retryable must NOT retry

    def test_auth_rejection_403_surfaces_unauthorized_and_no_retry(self) -> None:
        attempt_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            return _create_mock_response(
                status_code=403,
                json_data={"detail": "Forbidden token"},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="test-model",
            max_retries=3,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.UNAUTHORIZED
        assert exc_info.value.retryable is False
        assert attempt_count == 1

    def test_bad_request_400_surfaces_bad_request_and_no_retry(self) -> None:
        attempt_count = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempt_count
            attempt_count += 1
            return _create_mock_response(
                status_code=400,
                json_data={"error": {"message": "Invalid temperature parameter"}},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="test-model",
            max_retries=3,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.BAD_REQUEST
        assert exc_info.value.retryable is False
        assert attempt_count == 1

    def test_model_not_found_404_surfaces_model_not_loaded(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return _create_mock_response(
                status_code=404,
                json_data={"error": "model 'unknown-qwen' not found"},
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="unknown-qwen",
            max_retries=0,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.MODEL_NOT_LOADED
        assert exc_info.value.retryable is True

    def test_endpoint_not_found_404_without_model_surfaces_upstream_error(self) -> None:
        def handler(req: httpx.Request) -> httpx.Response:
            return _create_mock_response(
                status_code=404,
                text_data="404 Not Found",
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=0,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.UPSTREAM_ERROR
        assert exc_info.value.retryable is False

    def test_timeout_surfaces_timeout_error_and_retries(self) -> None:
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise httpx.ReadTimeout("Read timed out")
            return _create_mock_response(
                json_data={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Recovered after timeout"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=2,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        result = asyncio.run(provider.complete(_create_sample_request()))
        assert result.text == "Recovered after timeout"
        assert attempts == 2

    def test_persistent_timeout_exhausts_retries(self) -> None:
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectTimeout("Connect timed out")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=2,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.TIMEOUT
        assert exc_info.value.retryable is True
        assert attempts == 3  # 1 initial + 2 retries

    def test_network_connection_error_surfaces_unavailable(self) -> None:
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            raise httpx.ConnectError("Connection refused")

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=1,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.UNAVAILABLE
        assert exc_info.value.retryable is True
        assert attempts == 2

    def test_service_unavailable_503_and_429_surfaces_unavailable(self) -> None:
        for status in (503, 429):
            client = httpx.AsyncClient(
                transport=httpx.MockTransport(
                    lambda req, s=status: _create_mock_response(status_code=s)
                )
            )
            provider = OpenAICompatibleChatProvider(
                base_url="http://localhost:8090",
                model="qwen",
                max_retries=0,
                http_client=client,
            )
            with pytest.raises(WorkerError) as exc_info:
                asyncio.run(provider.complete(_create_sample_request()))
            assert exc_info.value.code == WorkerErrorCode.UNAVAILABLE
            assert exc_info.value.retryable is True

    def test_structured_worker_error_response_parsing(self) -> None:
        structured_payload = {
            "error": {
                "code": "model_not_loaded",
                "message": "Model 'qwen' is still loading in VRAM",
                "retryable": True,
                "request_id": "req-12345",
                "details": {"estimated_wait_seconds": 5},
            }
        }
        client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda req: _create_mock_response(status_code=503, json_data=structured_payload)
            )
        )
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=0,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.MODEL_NOT_LOADED
        assert exc_info.value.message == "Model 'qwen' is still loading in VRAM"
        assert exc_info.value.retryable is True
        assert exc_info.value.details == {"estimated_wait_seconds": 5}

    def test_structured_unauthorized_with_retryable_true_is_never_retried(self) -> None:
        """Upstream marking unauthorized as retryable must be ignored (local policy wins)."""
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return _create_mock_response(
                status_code=401,
                json_data={
                    "error": {
                        "code": "unauthorized",
                        "message": "Invalid token",
                        "retryable": True,  # Untrusted hint claiming retryable
                        "request_id": "req-unauth",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=3,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.UNAUTHORIZED
        assert exc_info.value.retryable is False
        assert attempts == 1  # Never retried

    def test_structured_bad_request_with_retryable_true_is_never_retried(self) -> None:
        """Upstream marking bad_request as retryable must be ignored (local policy wins)."""
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return _create_mock_response(
                status_code=400,
                json_data={
                    "error": {
                        "code": "bad_request",
                        "message": "Invalid parameters",
                        "retryable": True,  # Untrusted hint claiming retryable
                        "request_id": "req-bad",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=3,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.BAD_REQUEST
        assert exc_info.value.retryable is False
        assert attempts == 1  # Never retried

    def test_structured_error_code_wins_over_conflicting_http_status_unauthorized(self) -> None:
        """Structured error code 'unauthorized' wins even if HTTP status is 500."""
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return _create_mock_response(
                status_code=500,
                json_data={
                    "error": {
                        "code": "unauthorized",
                        "message": "Token expired in upstream",
                        "retryable": True,
                        "request_id": "req-conf-1",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=3,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.UNAUTHORIZED
        assert exc_info.value.retryable is False
        assert attempts == 1

    def test_structured_error_code_wins_over_conflicting_http_status_bad_request(self) -> None:
        """Structured error code 'bad_request' wins even if HTTP status is 500."""
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return _create_mock_response(
                status_code=500,
                json_data={
                    "error": {
                        "code": "bad_request",
                        "message": "Malformed payload in upstream",
                        "retryable": True,
                        "request_id": "req-conf-2",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=3,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.BAD_REQUEST
        assert exc_info.value.retryable is False
        assert attempts == 1

    def test_structured_error_code_wins_over_conflicting_http_status_model_not_loaded(self) -> None:
        """Structured error code 'model_not_loaded' wins even if HTTP status is 400."""
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return _create_mock_response(
                status_code=400,
                json_data={
                    "error": {
                        "code": "model_not_loaded",
                        "message": "Model booting",
                        "retryable": True,
                        "request_id": "req-conf-3",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=2,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.MODEL_NOT_LOADED
        assert exc_info.value.retryable is True
        assert attempts == 3

    def test_structured_error_code_wins_over_conflicting_http_status_timeout(self) -> None:
        """Structured error code 'timeout' wins even if HTTP status is 401."""
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return _create_mock_response(
                status_code=401,
                json_data={
                    "error": {
                        "code": "timeout",
                        "message": "Gateway timeout",
                        "retryable": True,
                        "request_id": "req-conf-4",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=2,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.TIMEOUT
        assert exc_info.value.retryable is True
        assert attempts == 3

    def test_structured_retryable_false_narrows_retryable_error_code(self) -> None:
        """Upstream advisory retryable=False narrows local retryable policy to False."""
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return _create_mock_response(
                status_code=503,
                json_data={
                    "error": {
                        "code": "model_not_loaded",
                        "message": "Model permanently failed to load",
                        "retryable": False,  # Narrowing advisory hint
                        "request_id": "req-narrow",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=3,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.MODEL_NOT_LOADED
        assert exc_info.value.retryable is False
        assert attempts == 1  # Narrowed to not retry

    def test_unrecognized_structured_code_falls_back_to_http_status(self) -> None:
        """Unrecognized error codes fall back to HTTP status mapping."""
        attempts = 0

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            return _create_mock_response(
                status_code=401,
                json_data={
                    "error": {
                        "code": "custom_vendor_unknown_error",
                        "message": "Bad authentication credentials",
                    }
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen",
            max_retries=3,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(provider.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.UNAUTHORIZED
        assert exc_info.value.retryable is False
        assert attempts == 1

    def test_retry_safety_does_not_mutate_request(self) -> None:
        attempts = 0
        received_payloads: list[dict[str, Any]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            nonlocal attempts
            attempts += 1
            received_payloads.append(json.loads(req.content.decode("utf-8")))
            if attempts == 1:
                return _create_mock_response(status_code=503, text_data="Busy")
            return _create_mock_response(
                json_data={
                    "choices": [
                        {
                            "message": {"role": "assistant", "content": "Success on retry"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        provider = OpenAICompatibleChatProvider(
            base_url="http://localhost:8090",
            model="qwen2.5-7b-instruct",
            max_retries=2,
            retry_backoff_seconds=0.01,
            http_client=client,
        )

        orig_req = _create_sample_request()
        orig_dict = orig_req.model_dump()
        result = asyncio.run(provider.complete(orig_req))

        assert result.text == "Success on retry"
        assert attempts == 2
        # Verify both payloads sent across wire are identical and original request unchanged
        assert received_payloads[0] == received_payloads[1]
        assert orig_req.model_dump() == orig_dict


@pytest.mark.unit
class TestFakeChatProvider:
    """Test deterministic FakeChatProvider functionality for CI and unit tests."""

    def test_default_deterministic_response(self) -> None:
        fake = FakeChatProvider(model="fake-model")
        req = _create_sample_request(
            messages=[
                ChatMessage(role="system", content="system prompt"),
                ChatMessage(role="user", content="Where is the school located?"),
            ]
        )
        result = asyncio.run(fake.complete(req))

        assert isinstance(result, CompletionResult)
        assert result.model == "fake-model"
        assert result.provider == "fake_chat"
        assert "Fake answer for: Where is the school located?" in result.text
        assert result.finish_reason == "stop"
        assert len(fake.calls) == 1
        assert fake.calls[0] == req

    def test_fake_chat_provider_repeatability_text(self) -> None:
        """Calling fake with the same request multiple times must produce byte-identical output."""
        fake = FakeChatProvider(model="fake-repeat-model")
        req = _create_sample_request(
            messages=[
                ChatMessage(role="system", content="system prompt"),
                ChatMessage(role="user", content="What is the legal deadline?"),
            ]
        )

        results: list[CompletionResult] = []
        for _ in range(5):
            res = asyncio.run(fake.complete(req))
            results.append(res)

        first_dump = results[0].model_dump_json()
        first_text = results[0].text
        for i, res in enumerate(results[1:], start=2):
            assert res.model_dump_json() == first_dump, f"Call {i} deviated from first dump"
            assert res.text == first_text, f"Call {i} text deviated from first text"
            assert res.finish_reason == "stop"
            assert res.model == "fake-repeat-model"
            assert res.usage.prompt_tokens == results[0].usage.prompt_tokens
            assert res.usage.completion_tokens == results[0].usage.completion_tokens
            assert res.usage.total_tokens == results[0].usage.total_tokens
        assert len(fake.calls) == 5

    def test_fake_chat_provider_repeatability_json(self) -> None:
        """Calling fake in JSON mode repeatedly must produce byte-identical output."""
        fake = FakeChatProvider(model="fake-json-model")
        req = _create_sample_request(
            messages=[
                ChatMessage(role="user", content="Extract metadata as JSON"),
            ],
            response_format="json_object",
        )

        results: list[CompletionResult] = []
        for _ in range(5):
            res = asyncio.run(fake.complete(req))
            results.append(res)

        first_dump = results[0].model_dump_json()
        first_text = results[0].text
        parsed_first = json.loads(first_text)
        assert "answer" in parsed_first

        for i, res in enumerate(results[1:], start=2):
            assert res.model_dump_json() == first_dump, f"JSON call {i} deviated from first dump"
            assert res.text == first_text
            assert json.loads(res.text) == parsed_first
        assert len(fake.calls) == 5

    def test_fake_chat_provider_invalid_pattern_raises(self) -> None:
        fake = FakeChatProvider()
        with pytest.raises(ValueError, match="pattern"):
            fake.set_canned("", "Empty pattern response")
        with pytest.raises(ValueError, match="pattern"):
            fake.set_canned("   ", "Whitespace pattern response")

    def test_default_json_response(self) -> None:
        fake = FakeChatProvider()
        req = _create_sample_request(response_format="json_object")
        result = asyncio.run(fake.complete(req))

        parsed = json.loads(result.text)
        assert "answer" in parsed
        assert "Fake answer for:" in parsed["answer"]

    def test_canned_responses_fifo_queue(self) -> None:
        fake = FakeChatProvider()
        fake.add_response("Canned response 1")
        fake.add_response("Canned response 2")
        fake.add_response(
            CompletionResult(
                text="Canned response 3",
                model="custom-fake",
                provider="fake_chat",
                finish_reason="length",
                usage=TokenUsage(prompt_tokens=5, completion_tokens=5, total_tokens=10),
            )
        )

        r1 = asyncio.run(fake.complete(_create_sample_request()))
        r2 = asyncio.run(fake.complete(_create_sample_request()))
        r3 = asyncio.run(fake.complete(_create_sample_request()))

        assert r1.text == "Canned response 1"
        assert r2.text == "Canned response 2"
        assert r3.text == "Canned response 3"
        assert r3.finish_reason == "length"
        assert len(fake.calls) == 3

    def test_canned_exception_raising(self) -> None:
        fake = FakeChatProvider()
        fake.add_response(
            WorkerError(
                WorkerErrorCode.UNAVAILABLE,
                "AI worker offline in test",
                retryable=True,
            )
        )

        with pytest.raises(WorkerError) as exc_info:
            asyncio.run(fake.complete(_create_sample_request()))

        assert exc_info.value.code == WorkerErrorCode.UNAVAILABLE
        assert exc_info.value.message == "AI worker offline in test"

    def test_pattern_matching_canned_responses(self) -> None:
        fake = FakeChatProvider()
        fake.set_canned("deadline", "Hạn nộp là ngày 15/09/2026.")
        fake.set_canned("kinh phí", "Tổng kinh phí là 500 triệu đồng.")

        req_deadline = _create_sample_request(
            messages=[ChatMessage(role="user", content="Có deadline nào không?")]
        )
        req_budget = _create_sample_request(
            messages=[ChatMessage(role="user", content="Hỏi về kinh phí thực hiện?")]
        )

        r_deadline = asyncio.run(fake.complete(req_deadline))
        r_budget = asyncio.run(fake.complete(req_budget))

        assert r_deadline.text == "Hạn nộp là ngày 15/09/2026."
        assert r_budget.text == "Tổng kinh phí là 500 triệu đồng."

    def test_custom_handler_callback(self) -> None:
        def custom_handler(req: CompletionRequest) -> str:
            last_msg = req.messages[-1].content
            return f"Processed: {last_msg.upper()}"

        fake = FakeChatProvider(handler=custom_handler)
        req = _create_sample_request(messages=[ChatMessage(role="user", content="hello world")])
        res = asyncio.run(fake.complete(req))
        assert res.text == "Processed: HELLO WORLD"

    def test_reset_clears_state(self) -> None:
        fake = FakeChatProvider()
        fake.add_response("queued")
        fake.set_canned("key", "val")
        asyncio.run(fake.complete(_create_sample_request()))
        assert len(fake.calls) == 1

        fake.reset()
        assert len(fake.calls) == 0
        assert len(fake.responses) == 0
        assert len(fake.canned_patterns) == 0

    def test_grounded_default_json_response_derives_citations(self) -> None:
        fake = FakeChatProvider()
        prompt_with_evidence = (
            "CÂU HỎI CỦA NGƯỜI DÙNG:\nSố văn bản là gì?\n\n"
            "BẰNG CHỨNG ĐƯỢC PHÉP SỬ DỤNG:\n"
            "<UNTRUSTED_DOCUMENT_DATA>\n[citation_id=c1]\n"
            "Số: 57/QĐ-UBND\n</UNTRUSTED_DOCUMENT_DATA>\n"
            "<UNTRUSTED_DOCUMENT_DATA>\n[citation_id=c2]\n"
            "ỦY BAN NHÂN DÂN XÃ MAI GIANG\n</UNTRUSTED_DOCUMENT_DATA>"
        )
        req = _create_sample_request(
            messages=[
                ChatMessage(role="system", content="system policy"),
                ChatMessage(role="user", content=prompt_with_evidence),
            ],
            response_format="json_object",
        )
        res = asyncio.run(fake.complete(req))
        parsed = json.loads(res.text)

        assert parsed["status"] == "answered"
        assert "citations" in parsed
        emitted_ids = {c["citation_id"] for c in parsed["citations"]}
        assert emitted_ids <= {"c1", "c2"}
        assert "c1" in emitted_ids
        assert "[c1]" in parsed["answer"]

    def test_grounded_default_json_response_abstains_without_evidence(self) -> None:
        fake = FakeChatProvider()
        prompt_no_evidence = "CÂU HỎI CỦA NGƯỜI DÙNG:\nThông tin không có trong tài liệu?\n"
        req = _create_sample_request(
            messages=[
                ChatMessage(role="system", content="system policy"),
                ChatMessage(role="user", content=prompt_no_evidence),
            ],
            response_format="json_object",
        )
        res = asyncio.run(fake.complete(req))
        parsed = json.loads(res.text)

        assert parsed["status"] == "insufficient_evidence"
        assert parsed["citations"] == []


@pytest.mark.unit
class TestSettingsLLMConfiguration:
    """Test that Settings contains Phase 4 LLM and model parameters."""

    def test_settings_llm_defaults(self) -> None:
        settings = Settings()
        assert settings.llm_base_url == "http://localhost:8090/v1"
        assert settings.llm_api_key == "local-fake-worker-token"
        assert settings.llm_model == "qwen2.5-7b-instruct"
        assert settings.llm_timeout_seconds == 30.0
        assert settings.llm_max_retries == 3
        assert settings.llm_retry_backoff_seconds == 0.5
        assert settings.embedding_base_url == "http://localhost:8090/v1"
        assert settings.embedding_model == "bge-m3"
        assert settings.reranker_model == "bge-reranker-v2-m3"
