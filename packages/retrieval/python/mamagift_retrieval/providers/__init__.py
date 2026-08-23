"""Provider interfaces and adapters for LLM and embedding backends.

Product code depends on the Protocols here, never on a concrete provider
(`docs/09_CODEX_EXECUTION.md` section 9). Each Protocol ships a deterministic
fake so CI never needs a real model, a GPU, or the network.
"""

from __future__ import annotations

from .bge_m3 import BgeM3EmbeddingProvider
from .chat import ChatCompletionProvider
from .embedding import EmbeddingProvider
from .fake_chat import FakeChatProvider
from .fake_embedding import FakeEmbeddingProvider
from .openai_compatible import OpenAICompatibleChatProvider

__all__ = [
    "BgeM3EmbeddingProvider",
    "ChatCompletionProvider",
    "EmbeddingProvider",
    "FakeChatProvider",
    "FakeEmbeddingProvider",
    "OpenAICompatibleChatProvider",
]
