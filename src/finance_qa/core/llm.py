"""Shared LLM layer: connection config + one unified client.

This is the neutral home for the vLLM/DeepInfra connection config that used to
live inside ``retrieval.judge`` (a retrieval module owning LLM config was a
backwards dependency). ``retrieval.judge``, ``graph`` nodes, and ``planning``
all import from here now.

Async is the native shape: a question spends nearly all its wall clock waiting
on this endpoint (1 understand call + 1 judge call + up to 10 REPL turns), so the
batch runner drives many questions concurrently on one event loop. ``achat`` and
``get_chat_model`` are the real implementations; ``chat`` is a sync wrapper for
the offline scripts.

Two clients, one config:
- ``achat(messages, ...)`` / ``chat(...)`` — a JSON POST returning the reply
  text. Folds in the local-vLLM vs DeepInfra branching that was duplicated
  across ``judge.call_llm`` and ``understand._post``.
- ``get_chat_model(...)`` — a langchain ``ChatOpenAI`` factory for the callers
  that need structured output or tool-calling (``bind_tools`` / ``tool_choice``).

Override the backend via env without touching code:
    LLM_ENDPOINT=https://api.deepinfra.com/v1/openai/chat/completions
    LLM_MODEL=Qwen/Qwen3-14B
    LLM_API_KEY=$DEEPINFRA_API_KEY
"""
from __future__ import annotations

import os
from typing import Any

from finance_qa.core.http import client, pool, run_sync

ENDPOINT = os.environ.get("LLM_ENDPOINT", "http://127.0.0.1:8990/v1/chat/completions")
# The id the vLLM server on 8990 actually reports at `/v1/models`. Use the full HF
# repo id, not a bare alias: aliases come from the server's `--served-model-name`
# flag and vanish on a restart with different flags, which is exactly how the
# 85-question retry pool on 2026-08-23 died (every call 404'd, every answer 0.0,
# the failure buried in the per-question `errors` list). `run_graph.py` now
# preflights this id against `/v1/models` so the next mismatch fails loudly.
MODEL = os.environ.get("LLM_MODEL", "Qwen/Qwen3.5-9B")
API_KEY = os.environ.get("LLM_API_KEY", "")


def _request(
    messages: list[dict[str, str]],
    thinking: bool,
    max_tokens: int | None,
    temperature: float,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Body + headers for either backend.

    A local vLLM server toggles thinking via ``chat_template_kwargs``; DeepInfra's
    Qwen3 has thinking on by default and disables it with a ``/no_think`` prefix on
    the last user turn.
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
        return body, {"Authorization": f"Bearer {API_KEY}"}

    body = {
        "model": MODEL,
        "messages": messages,
        "max_tokens": max_tokens or (4096 if thinking else 256),
        "temperature": temperature,
        "chat_template_kwargs": {"enable_thinking": thinking},
    }
    return body, {}


async def achat(
    messages: list[dict[str, str]],
    *,
    thinking: bool = False,
    max_tokens: int | None = None,
    timeout: int = 600,
    temperature: float = 0.0,
) -> str:
    """POST ``messages`` to the chat endpoint and return the reply text."""
    body, headers = _request(messages, thinking, max_tokens, temperature)
    response = await client().post(ENDPOINT, json=body, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def chat(
    messages: list[dict[str, str]],
    *,
    thinking: bool = False,
    max_tokens: int | None = None,
    timeout: int = 600,
    temperature: float = 0.0,
) -> str:
    """Sync wrapper over ``achat`` for offline scripts."""
    return run_sync(
        achat(
            messages,
            thinking=thinking,
            max_tokens=max_tokens,
            timeout=timeout,
            temperature=temperature,
        )
    )


def get_chat_model(
    *,
    model: str = MODEL,
    thinking: bool = True,
    max_tokens: int = 2048,
    timeout: int = 120,
    temperature: float = 0.0,
):
    """langchain ``ChatOpenAI`` bound to this backend, one instance per config.

    Cached, because a fresh ``ChatOpenAI`` builds its own httpx connection pool and
    the 7 call sites each constructed one *per question* -- roughly 8,000 pools
    over a 1,012-question run. Keyed by event loop as well as config, for the
    reason in ``core.http.pool``.

    Imported lazily so modules that only need ``achat()`` don't pull in langchain.
    ``temperature`` defaults to 0.0 (deterministic) for every existing caller; the
    REPL solver raises it so its tool-calling loop can escape a repeated dead end.
    """
    key = ("chat_model", model, thinking, max_tokens, timeout, temperature)
    cache = pool()
    if key not in cache:
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
        cache[key] = ChatOpenAI(**kwargs)
    return cache[key]
