"""Runtime configuration objects."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMConfig:
    """Connection settings for chat/model clients."""

    endpoint: str = "http://127.0.0.1:8990/v1/chat/completions"
    model: str = "Qwen/Qwen3-8B-Instruct"
    api_key: str = ""

    @classmethod
    def from_env(cls) -> "LLMConfig":
        return cls(
            endpoint=os.environ.get("LLM_ENDPOINT", cls.endpoint),
            model=os.environ.get("LLM_MODEL", cls.model),
            api_key=os.environ.get("LLM_API_KEY", ""),
        )

    @property
    def base_url(self) -> str:
        return self.endpoint.replace("/chat/completions", "")


DEFAULT_LLM_CONFIG = LLMConfig.from_env()
LLM_ENDPOINT = DEFAULT_LLM_CONFIG.endpoint
LLM_MODEL = DEFAULT_LLM_CONFIG.model
LLM_API_KEY = DEFAULT_LLM_CONFIG.api_key
