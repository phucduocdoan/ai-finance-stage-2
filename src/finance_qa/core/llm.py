"""Shared LLM layer: connection config + one unified client.

This is the neutral home for the vLLM/DeepInfra connection config that used to
live inside ``retrieval.judge`` (a retrieval module owning LLM config was a
backwards dependency). ``retrieval.judge``, ``graph`` nodes, and ``planning``
all import from here now.

Two clients, one config:
- ``chat(messages, ...)``  — a plain urllib POST returning the reply text. Folds
  in the local-vLLM vs DeepInfra branching that was duplicated across
  ``judge.call_llm`` and ``understand._post``.
- ``get_chat_model(...)`` — a langchain ``ChatOpenAI`` factory for the one caller
  (``formula``) that needs tool-calling (``bind_tools`` / ``tool_choice``).

Override the backend via env without touching code:
    LLM_ENDPOINT=https://api.deepinfra.com/v1/openai/chat/completions
    LLM_MODEL=Qwen/Qwen3-14B
    LLM_API_KEY=$DEEPINFRA_API_KEY
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://127.0.0.1:8990/v1/chat/completions")
MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen3-8B-Instruct")
API_KEY = os.environ.get("LLM_API_KEY", "")


def chat(
    messages: list[dict[str, str]],
    *,
    thinking: bool = False,
    max_tokens: int | None = None,
    timeout: int = 600,
    temperature: float = 0.0,
) -> str:
    """POST ``messages`` to the chat endpoint and return the reply text.

    Handles both backends: a local vLLM server toggles thinking via
    ``chat_template_kwargs``; DeepInfra's Qwen3 has thinking on by default and
    disables it with a ``/no_think`` prefix on the last user turn.
    """
    if API_KEY:
        msgs = messages
        if not thinking:
            msgs = [dict(m) for m in messages]
            for m in reversed(msgs):
                if m.get("role") == "user":
                    m["content"] = f"/no_think\n{m['content']}"
                    break
        body: dict[str, Any] = {
            "model": MODEL,
            "messages": msgs,
            "max_tokens": max_tokens or (8192 if thinking else 4096),
            "temperature": temperature,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        }
    else:
        body = {
            "model": MODEL,
            "messages": messages,
            "max_tokens": max_tokens or (4096 if thinking else 256),
            "temperature": temperature,
            "chat_template_kwargs": {"enable_thinking": thinking},
        }
        headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(ENDPOINT, data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())["choices"][0]["message"]["content"]


def get_chat_model(
    *,
    model: str = MODEL,
    thinking: bool = True,
    max_tokens: int = 2048,
    timeout: int = 120,
    temperature: float = 0.0,
):
    """langchain ``ChatOpenAI`` bound to this backend (for tool-calling callers).

    Imported lazily so modules that only need ``chat()`` don't pull in langchain.
    ``temperature`` defaults to 0.0 (deterministic) for every existing caller; the
    REPL solver raises it so its tool-calling loop can escape a repeated dead end.
    """
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": ENDPOINT.replace("/chat/completions", ""),
        "api_key": API_KEY or "none",
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": timeout,
    }
    if "Qwen" in model:
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": thinking}}
    return ChatOpenAI(**kwargs)
