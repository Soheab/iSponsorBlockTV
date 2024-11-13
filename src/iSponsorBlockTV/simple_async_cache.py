# COPIED AND MODIFIED FROM
# - https://gist.github.com/trevorflahardy/6c2ba491a96cfe1e8f86d06ba6d26398
# - https://github.com/mikeshardmind/async-utils/blob/62bd8af26a6d7dd7464273238da11e377a0cfe16/async_utils/task_cache.py

from __future__ import annotations

import asyncio
import datetime
import functools
import time
from collections.abc import Callable, Coroutine, Hashable
from typing import TYPE_CHECKING, Any, ParamSpec, Self, overload

from .cache_key import make_key

P = ParamSpec("P")

type CachedMethod[**P, _VT] = Callable[
    P, _VT
]
type CachedFunction[**P, _VT] = Callable[
    P, _VT
]

type CachedFunc[**P, _VT] = CachedFunction[P, _VT]

if TYPE_CHECKING:
    type CachedFuncDeco[**P, _VT] = Callable[
        [CachedFunc[P, _VT]], CachedFunc[P, _VT]
    ]

    type AsyncCachedFunc[**P, _VT] = CachedFunc[P, Coroutine[Any, Any, _VT]]
    type AsyncCachedMethod[**P, _VT] = CachedMethod[P, Coroutine[Any, Any, _VT]]

    type AsyncCachedFuncDeco[**P, _VT] = Callable[
        [CachedFunc[P, Coroutine[Any, Any, _VT]]],
        CachedFunc[P, asyncio.Task[_VT]],
    ]

type InV[_VT] = tuple[_VT, float]


class _NOTHING:
    __slots__ = ()

    def __eq__(self, other: Any) -> bool:
        return False

    def __bool__(self) -> bool:
        return False

    def __hash__(self) -> int:
        return 0

    def __repr__(self):
        return "..."


NOTHING: Any = _NOTHING()


class ExpiryCache[_KT: Hashable, _VT](dict[_KT, tuple[_VT, float]]):
    """Denotes an expiration cache that will remove items after a certain amount of time has passed since they were added.
    .. container:: operations
        .. describe:: cache[key]
            Returns the value of the key in the cache. If the key is not in the cache, a :exc:`KeyError` is raised.
        .. describe:: cache[key] = value
            Sets the key in the cache to the value.
        .. describe:: cache.get(key[, default])
            Returns the value of the key in the cache. If the key is not in the cache, the default value is returned.
        .. describe:: cache.pop(key[, default])
            Removes the key from the cache and returns the value. If the key is not in the cache, the default value
            is returned.

    Parameters
    -----------
    delta: :class:`datetime.timedelta`
        The amount of time to keep the items in the cache for. This is the time difference between when the item was added
        and when it will be removed.
    **kwargs: Any
        Any keyword arguments to pass to the :class:`dict` constructor.
    """

    def __init__(
        self,
        delta: datetime.timedelta | float,
        *,
        maxsize: int = NOTHING,
        **kwargs: Any,
    ) -> None:
        self.__live_time: float = (
            delta
            if not isinstance(delta, datetime.timedelta)
            else delta.total_seconds()
        )

        self.maxsize: int = maxsize
        super().__init__(**kwargs)

    @classmethod
    def wrap(
        cls: type[Self],
        delta: datetime.timedelta | float,
        *,
        maxsize: int = NOTHING,
        **kwargs: Any,
    ) -> CachedFuncDeco[P, _VT]:
        def inner(func: CachedFunc[P, _VT]) -> CachedFunc[P, _VT]:
            EXPIRY_CACHE = cls(delta, maxsize=maxsize, **kwargs)

            @functools.wraps(func)
            def wrapped(*args: P.args, **kwargs: P.kwargs) -> _VT:
                key: _KT = make_key(args, kwargs)  # type: ignore
                try:
                    return EXPIRY_CACHE[key]
                except KeyError:
                    EXPIRY_CACHE[key] = item = func(*args, **kwargs)
                    return item

            return wrapped

        return inner
    

    @classmethod
    def wrap_async(
        cls: type[ExpiryCache[_KT, asyncio.Task[_VT]]],
        delta: datetime.timedelta | float,
        *,
        maxsize: int = NOTHING,
        **kwargs: Any,
    ) -> AsyncCachedFuncDeco[P, _VT]:
        def inner(
            func: CachedFunc[P, Coroutine[Any, Any, _VT]],
        ) -> CachedFunc[P, asyncio.Task[_VT]]:
            EXPIRY_CACHE = cls(delta, maxsize=maxsize, **kwargs)

            @functools.wraps(func)
            def wrapped(*args: P.args, **kwargs: P.kwargs) -> asyncio.Task[_VT]:
                key: _KT = make_key(args, kwargs)  # type: ignore
                try:
                    return EXPIRY_CACHE[key]
                except KeyError:
                    EXPIRY_CACHE[key] = task = asyncio.create_task(func(*args, **kwargs))
                    # This results in internal_cache.pop(key, task) later
                    # while avoiding a late binding issue with a lambda instead
                    call_after_ttl = functools.partial(
                        asyncio.get_running_loop().call_later,
                        delta if not isinstance(delta, datetime.timedelta) else delta.total_seconds(),
                        EXPIRY_CACHE.pop,
                        key,
                    )
                    task.add_done_callback(call_after_ttl)  # type: ignore
                    return task

            return wrapped

        return inner

    def _verify_cache(self) -> None:
        now = time.time()
        for k, (i, t) in self.copy().items():
            # If the time difference between now and the time the item was added is greater than the live time
            if isinstance(i, asyncio.Task) and (i.done() or i.cancelled()):
                self.__delitem__(k)
                continue
            if (now - t) > self.__live_time:
                self.__delitem__(k)

    def __setitem__(self, __k: _KT, __v: _VT) -> None:
        self._verify_cache()
        _v: InV[_VT] = (__v, time.time())
        super().__setitem__(__k, _v)
        if len(self) > self.maxsize:
            self.pop(next(iter(self)))

    def __getitem__(self, __k: _KT) -> _VT:
        self._verify_cache()
        result: InV[_VT] = super().__getitem__(__k)
        return result[0]

    def __contains__(self, key: _KT) -> bool:
        self._verify_cache()
        return super().__contains__(key)

    @property
    def delta(self) -> datetime.timedelta:
        """:class:`datetime.timedelta`: The amount of time to keep the items in the cache for."""
        return datetime.timedelta(seconds=self.__live_time)

    @delta.setter
    def delta(self, new: datetime.timedelta) -> None:
        self.__live_time = new.total_seconds()
        self._verify_cache()

    @overload
    def pop(self, key: _KT, /) -> _VT: ...

    @overload
    def pop(self, key: _KT, default: _VT, /) -> _VT: ...

    @overload
    def pop[_T](self, key: _KT, default: _T, /) -> _VT | _T: ...

    def pop[_T](self, key: _KT, default: _VT | _T = NOTHING, /) -> _VT | _T:
        """Pops a key from the cache, returning the value. If the key is not in the cache, the default value is returned, or
        a :exc:`KeyError` is raised if no default value was provided.

        Parameters
        -----------
        key: _KT
            The key to pop from the cache.
        default: Optional[_VT]
            The default value to return if the key is not in the cache. If not provided, a :exc:`KeyError` is raised
            when there is no key to remove.

        Returns
        --------
        _VT
            The value of the key in the cache.
        """
        self._verify_cache()

        # If the key is not in the cache
        if key not in self:
            # If a default value was provided, return it
            if default is not NOTHING:
                return default

            # Otherwise,
            raise KeyError(key)

        # This key is in the cache, return the value
        result: InV[_VT] = super().pop(key)
        return result[0]

    @overload
    def get(self, key: _KT) -> _VT | None: ...

    @overload
    def get(self, key: _KT, default: None) -> _VT | None: ...

    @overload
    def get(self, key: _KT, default: _VT) -> _VT: ...

    @overload
    def get[_T](self, key: _KT, default: _T) -> _VT | _T: ...

    def get[_T](self, key: _KT, default: _VT | _T = NOTHING) -> _VT | _T | None:
        """Gets a key from the cache, returning the value. If the key is not in the cache, the default value is
        returned, or ``None`` is returned if no default value was provided.

        Parameters
        -----------
        key: _KT
            The key to get from the cache.
        default: Optional[_VT]
            The default value to return if the key is not in the cache. If not provided, ``None`` is returned.
        """
        self._verify_cache()

        if key not in self:
            if default is not NOTHING:
                return default

            return None

        result: InV[_VT] = super().__getitem__(key)
        return result[0]
