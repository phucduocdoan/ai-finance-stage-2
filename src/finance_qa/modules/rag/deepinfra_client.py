"""Shared DeepInfra HTTP client.

Embedding and reranking are different RAG capabilities, but they use the same
DeepInfra auth and retry policy. Keeping that plumbing in a class gives callers a
single object to replace with an async implementation later.
"""
from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from typing import Any

import httpx

from finance_qa.core.http import client as http_client
from finance_qa.core.http import run_sync
from finance_qa.core.paths import PROJECT_ROOT


BASE_URL = "https://api.deepinfra.com"
EMBED_URL = f"{BASE_URL}/v1/openai/embeddings"
INFERENCE_URL = f"{BASE_URL}/v1/inference"
TIMEOUT = 120
RETRIES = 4


class DeepInfraError(RuntimeError):
    """An API call that retrying will not fix, or did not recover after retries."""


def api_key() -> str:
    key = os.environ.get("DEEPINFRA_API_KEY", "").strip()
    if key:
        return key
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "DEEPINFRA_API_KEY" and value.strip():
                return value.strip()
    raise DeepInfraError("DEEPINFRA_API_KEY is not set (environment or .env)")


@dataclass(frozen=True)
class DeepInfraClient:
    """Async HTTP client over the shared connection pool.

    `apost` is the implementation; `post` is the sync wrapper the offline index
    builders use. The retry backoff sleeps on the event loop, so a retrying
    reranker call no longer parks a thread for up to 8 seconds.
    """

    key: str | None = None
    timeout: int = TIMEOUT
    retries: int = RETRIES

    def resolved_key(self) -> str:
        return self.key or api_key()

    async def apost(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON with backoff. 4xx is terminal; 5xx and transport errors retry."""
        headers = {"Authorization": f"Bearer {self.resolved_key()}"}
        last = ""
        for attempt in range(self.retries):
            try:
                response = await http_client().post(
                    url, json=payload, headers=headers, timeout=self.timeout
                )
                if response.status_code >= 400:
                    detail = response.text[:400]
                    if response.status_code < 500 and response.status_code != 429:
                        raise DeepInfraError(
                            f"HTTP {response.status_code} from {url}: {detail}"
                        )
                    last = f"HTTP {response.status_code}: {detail}"
                else:
                    return response.json()
            except (httpx.HTTPError, json.JSONDecodeError) as exc:
                last = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries - 1:
                await asyncio.sleep(2**attempt)
        raise DeepInfraError(f"{url} failed after {self.retries} attempts: {last}")

    def post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        return run_sync(self.apost(url, payload))
