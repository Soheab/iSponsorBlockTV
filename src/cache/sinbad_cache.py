#   Copyright 2020-present Michael Hall
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.
# source: https://github.com/mikeshardmind/async-utils/blob/2fff43d35428937bbf6aa253d8d729db7cf3599e/async_utils/task_cache.py
# modified to fit my needs

from __future__ import annotations
from typing import Any, TypeVar, ParamSpec
from collections.abc import Callable, Hashable, Coroutine, Generator

import asyncio
from functools import partial

from .cache_key import make_key

__all__ = ("taskcache", "LRU", "lrutaskcache")


P = ParamSpec("P")
T = TypeVar("T")


class TaskWrapper[T](asyncio.Task[T]):
    def __await__(self) -> Generator[Any, Any, Any | object | tuple[()] | tuple[Any]]:
        res = yield from super().__await__()
        if isinstance(res, tuple) and len(res) > 1:
            return res[0]

        return res


class LRU[K, V]:
    def __init__(self, maxsize: int, /) -> None:
        self.cache: dict[K, V] = {}
        self.maxsize: int = maxsize

    def get(self, key: K, default: T, /) -> V | T:
        if key not in self.cache:
            return default
        self.cache[key] = self.cache.pop(key)
        return self.cache[key]

    def __getitem__(self, key: K, /) -> V:
        self.cache[key] = self.cache.pop(key)
        return self.cache[key]

    def __setitem__(self, key: K, value: V, /) -> None:
        self.cache[key] = value
        if len(self.cache) > self.maxsize:
            self.cache.pop(next(iter(self.cache)))

    def remove(self, key: K) -> None:
        self.cache.pop(key, None)


def taskcache(
    ttl: float | None = None,
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, asyncio.Task[T]]]:
    """Decorator to modify coroutine functions to instead act as functions returning cached tasks.

    For general use, this leaves the end user API largely the same,
    while leveraging tasks to allow preemptive caching.

    Note: This uses the args and kwargs of the original coroutine function as a cache key.
    This includes instances (self) when wrapping methods.
    Consider not wrapping instance methods, but what those methods call when feasible in cases where this may matter.

    The ordering of args and kwargs matters."""

    def wrapper(
        coro: Callable[P, Coroutine[Any, Any, T]]
    ) -> Callable[P, asyncio.Task[T]]:
        internal_cache: dict[Hashable, asyncio.Task[T]] = {}

        def wrapped(*args: P.args, **kwargs: P.kwargs) -> asyncio.Task[T]:
            key = make_key(args, kwargs)
            try:
                return internal_cache[key]
            except KeyError:
                internal_cache[key] = task = asyncio.create_task(coro(*args, **kwargs))
                if ttl is not None:
                    # This results in internal_cache.pop(key, task) later
                    # while avoiding a late binding issue with a lambda instead
                    call_after_ttl = partial(
                        asyncio.get_running_loop().call_later,
                        ttl,
                        internal_cache.pop,
                        key,
                    )
                    task.add_done_callback(call_after_ttl)
                return task

        return wrapped

    return wrapper


def _lru_evict(
    ttl: float,
    cache: LRU[Hashable, Any],
    key: Hashable,
    task: asyncio.Task[tuple[list[Any], bool]],
) -> None:
    if task.cancelled():
        cache.remove(key)
        return

    if task.done() and (result := task.result()) and len(result) > 1 and result[1]:
        cache.remove(key)
        return

    asyncio.get_running_loop().call_later(ttl, cache.remove, key)


def lrutaskcache(
    ttl: float | None = None, maxsize: int = 1024
) -> Callable[[Callable[P, Coroutine[Any, Any, T]]], Callable[P, asyncio.Task[T]]]:
    """Decorator to modify coroutine functions to instead act as functions returning cached tasks.

    For general use, this leaves the end user API largely the same,
    while leveraging tasks to allow preemptive caching.

    Note: This uses the args and kwargs of the original coroutine function as a cache key.
    This includes instances (self) when wrapping methods.
    Consider not wrapping instance methods, but what those methods call when feasible in cases where this may matter.

    The ordering of args and kwargs matters.

    tasks are evicted by LRU and ttl.
    """

    def wrapper(
        coro: Callable[P, Coroutine[Any, Any, T]]
    ) -> Callable[P, asyncio.Task[T]]:
        internal_cache: LRU[Hashable, asyncio.Task[T]] = LRU(maxsize)

        def wrapped(*args: P.args, **kwargs: P.kwargs) -> asyncio.Task[T]:
            key = make_key(args, kwargs)
            try:
                return internal_cache[key]
            except KeyError:
                internal_cache[key] = task = TaskWrapper(coro(*args, **kwargs))
                if ttl:
                    task.add_done_callback(partial(_lru_evict, ttl, internal_cache, key))  # type: ignore
                return task

        return wrapped

    return wrapper
