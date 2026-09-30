"""Configured LangChain models; provider SDKs own messages and tool-call parsing."""

from __future__ import annotations

import os

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_anthropic import ChatAnthropic
from langchain_openrouter import ChatOpenRouter

from code_identity import capture_module
capture_module()

LLMClient = BaseChatModel
MAX_TOKENS = 8000
REQUEST_TIMEOUT = 180
DEFAULT_MODELS = {"openrouter": "minimax/minimax-m3", "minimax": "MiniMax-M3"}
MINIMAX_BASE_URL = "https://api.minimax.io/anthropic"


def resolve_provider() -> str:
    return os.environ.get("PROVIDER", "").strip().lower() or (
        "minimax" if os.environ.get("MINIMAX_API_KEY") else "openrouter"
    )


def default_model(provider: str | None = None) -> str:
    return os.environ.get("MODEL") or DEFAULT_MODELS.get(provider or resolve_provider(), DEFAULT_MODELS["openrouter"])


def model_identity(model: BaseChatModel) -> dict:
    metadata = model.metadata if isinstance(model.metadata, dict) else {}
    name = getattr(model, "model", None) or getattr(model, "model_name", None)
    return {"provider": metadata.get("provider", "offline"), "model": metadata.get("model", name or "scripted")}


def with_reasoning(model: BaseChatModel, enabled: bool) -> BaseChatModel:
    if isinstance(model, ChatAnthropic):
        return model.model_copy(update={"thinking": {"type": "adaptive" if enabled else "disabled"}})
    if isinstance(model, ChatOpenRouter):
        return model.model_copy(update={"reasoning": {"enabled": enabled}})
    return model


def load_llm(model: str | None = None, provider: str | None = None) -> BaseChatModel:
    provider = (provider or resolve_provider()).strip().lower()
    name = model or default_model(provider)
    if provider not in DEFAULT_MODELS:
        raise RuntimeError(f"Unknown PROVIDER={provider!r}. Use 'minimax' or 'openrouter'.")
    key_name = "MINIMAX_API_KEY" if provider == "minimax" else "OPENROUTER_API_KEY"
    key = os.environ.get(key_name)
    if not key:
        raise RuntimeError(f"{key_name} is not set. Configure it in the environment or .env file.")
    settings = dict(model=name, max_tokens=MAX_TOKENS, max_retries=0,
                    metadata={"provider": provider, "model": name})
    if provider == "minimax":
        client = ChatAnthropic(api_key=key, base_url=MINIMAX_BASE_URL, timeout=REQUEST_TIMEOUT, **settings)
    else:
        # The OpenRouter SDK takes milliseconds; 180 here meant 0.18 s and hung the first request.
        client = ChatOpenRouter(api_key=key, timeout=REQUEST_TIMEOUT * 1000, **settings)
    return with_reasoning(client, os.environ.get("REASONING", "1").lower() not in ("0", "false", "no"))