"""Shared async HTTP plumbing: one connection pool per event loop.

Everything that leaves this process over HTTP -- the LLM endpoint, the DeepInfra
reranker -- goes through the same `httpx.AsyncClient` so a 1,012-question run
opens one connection pool instead of one per call.

Why not `@lru_cache` on the client factory: an `httpx.AsyncClient` binds to the
event loop that created it, and every sync entry point here opens a fresh loop
via `asyncio.run`. A cache keyed only by config would hand a dead loop's client
to a live loop (`RuntimeError: Event loop is closed`). So the cache is keyed by
the running loop, in a `WeakKeyDictionary` so a finished loop's clients become
collectable.

No lock either, unlike `rag.service.get_retriever`: a coroutine cannot be
preempted between the `get` and the `set` below, and two event loops never share
an entry. Thread-based caches need a lock precisely because they can be.
"""
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, TypeVar
from weakref import WeakKeyDictionary

import httpx

T = TypeVar("T")

# Generous: the batch runner's concurrency cap is what limits real load, and a
# pool smaller than that cap turns into invisible queueing.
LIMITS = httpx.Limits(max_connections=256, max_keepalive_connections=64)
# The judge with thinking on can take minutes; connect should fail fast.
TIMEOUT = httpx.Timeout(600.0, connect=15.0)

_pools: WeakKeyDictionary[Any, dict[Any, Any]] = WeakKeyDictionary()
_pool_no_loop: dict[Any, Any] = {}


def loop_cache() -> dict[Any, Any]:
    """The per-event-loop cache of loop-bound objects (clients, chat models).

    Named for what it holds, not for `LIMITS` above -- that's the actual httpx
    connection pool; this is the dict that hands each event loop its own client.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called from synchronous code: nothing here is loop-bound yet, and the
        # sync wrappers below each open and close their own loop.
        return _pool_no_loop
    cached = _pools.get(loop)
    if cached is None:
        cached = _pools[loop] = {}
    return cached


def client() -> httpx.AsyncClient:
    """Pooled `AsyncClient` for the current event loop."""
    cache = loop_cache()
    existing = cache.get("httpx")
    if existing is None or existing.is_closed:
        existing = cache["httpx"] = httpx.AsyncClient(timeout=TIMEOUT, limits=LIMITS)
    return existing


def run_sync(coro: Awaitable[T]) -> T:
    """Run `coro` to completion from synchronous code.

    Every sync wrapper in the codebase funnels through here, so there is one
    place that fails loudly instead of deadlocking when it is reached from
    inside a running loop -- in that case the caller wants the async variant.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    getattr(coro, "close", lambda: None)()
    raise RuntimeError(
        "sync wrapper called from a running event loop; await the async variant"
    )
