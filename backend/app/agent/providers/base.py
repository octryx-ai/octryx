"""Base LLM Provider – unified interface for all LLM backends.

Every driver's ``chat`` is wrapped once per class (``__init_subclass__``): it is measured (octryx_llm_* on
/metrics) and runs under the platform's content policies (``services/content_security/model_call``), the one
enforcement point every driver call passes.
"""

import asyncio
import functools
import inspect
import time
from abc import ABC, abstractmethod
from contextvars import ContextVar
from typing import Any

from ...services.observability import agent_metrics

# A provider's chat that calls another provider's chat (a fallback, a wrapper) is one request, counted once.
_IN_CHAT: ContextVar[bool] = ContextVar("octryx_llm_in_chat", default=False)


def _measured(chat: Any, provider: str) -> Any:
    """``chat`` under the content policies that also counts the request, its outcome and its duration."""
    signature = inspect.signature(chat)

    @functools.wraps(chat)
    async def measured(self: Any, *args: Any, **kwargs: Any) -> Any:
        if _IN_CHAT.get():
            return await chat(self, *args, **kwargs)
        model = kwargs.get("model", args[1] if len(args) > 1 else "")
        token, started, outcome = _IN_CHAT.set(True), time.perf_counter(), "error"
        try:
            from ...services.content_security.model_call import enforced_chat

            result = await enforced_chat(self, chat, signature, args, kwargs)
            outcome = "ok"
            return result
        except TimeoutError:
            outcome = "timeout"
            raise
        except asyncio.CancelledError:
            outcome = "cancelled"
            raise
        finally:
            _IN_CHAT.reset(token)
            agent_metrics.record_llm_request(getattr(self, "name", provider) or provider, str(model or "unknown"),
                                             outcome, time.perf_counter() - started)

    return measured


class BaseLLMProvider(ABC):
    """Abstract base class for LLM providers."""

    name: str = "base"

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        chat = cls.__dict__.get("chat")
        if chat is not None and inspect.iscoroutinefunction(chat) and not getattr(chat, "__isabstractmethod__", False):
            cls.chat = _measured(chat, cls.name)  # type: ignore[method-assign]

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        model: str,
        tools: list[dict] | None = None,
        temperature: float = 0,
        max_tokens: int = 4096,
        reasoning_effort: str | None = None,
    ) -> dict[str, Any]:
        """
        Send a chat completion request.

        Returns dict with:
            - content: str
            - tool_calls: list | None
            - usage: dict (prompt_tokens, completion_tokens)
            - model: str
        """
        ...

    def content_route(self, model: str) -> Any:
        """The governed gateway route the custom content policies decide on, or ``None`` (a direct driver)."""
        return None

    @abstractmethod
    async def list_models(self) -> list[dict]:
        """List available models. Returns list of model dicts."""
        ...

    @abstractmethod
    async def close(self):
        """Clean up resources."""
        ...
