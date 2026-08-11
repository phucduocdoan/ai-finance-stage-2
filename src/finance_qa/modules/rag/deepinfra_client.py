"""Shared DeepInfra HTTP client.

Embedding and reranking are different RAG capabilities, but they use the same
DeepInfra auth and retry policy. Keeping that plumbing in a class gives callers a
single object to replace with an async implementation later.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

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
    """Synchronous HTTP client with an async-compatible boundary.

    `apost()` currently delegates to a thread. A real aiohttp/httpx transport can
    replace this class without changing embedder/reranker APIs.
    """

    key: str | None = None
    timeout: int = TIMEOUT
    retries: int = RETRIES

    def resolved_key(self) -> str:
        return self.key or api_key()

    def post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON with backoff. 4xx is terminal; 5xx and transport errors retry."""
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {self.resolved_key()}",
            "Content-Type": "application/json",
        }
        last = ""
        for attempt in range(self.retries):
            request = urllib.request.Request(url, data=body, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read())
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                if exc.code < 500 and exc.code != 429:
                    raise DeepInfraError(f"HTTP {exc.code} from {url}: {detail}") from exc
                last = f"HTTP {exc.code}: {detail}"
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last = f"{type(exc).__name__}: {exc}"
            if attempt < self.retries - 1:
                time.sleep(2**attempt)
        raise DeepInfraError(f"{url} failed after {self.retries} attempts: {last}")

    async def apost(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Async facade for future gather-based pipelines."""
        return await asyncio.to_thread(self.post, url, payload)
