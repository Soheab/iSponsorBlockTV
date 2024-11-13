import datetime
from collections.abc import Callable, Hashable
from typing import TYPE_CHECKING, Any

from cache.lru import LRU

from .cache_key import make_key

__all__ = ("AsyncConditionalTTL",)


class AsyncConditionalTTL:
    class _TTL(LRU):
        def __init__(self, time_to_live: int | float, maxsize: int) -> None:
            super().__init__(maxsize=maxsize)

            self.time_to_live: datetime.timedelta | None = (
                datetime.timedelta(seconds=time_to_live) if time_to_live else None
            )

            self.maxsize: int = maxsize

        def _verify_cache(self) -> None:
            if self.maxsize is not None and len(self) > self.maxsize:
                self.popitem()

            if self.time_to_live:
                for key in list(self):
                    if key not in self:
                        continue

                    key_expiration = super().__getitem__(key)[1]
                    if key_expiration and key_expiration < datetime.datetime.now(
                        tz=datetime.UTC
                    ):
                        del self[key]


        def __contains__(self, key: Hashable) -> bool:
            if key not in self:
                return False

            key_expiration = super().__getitem__(key)[1]
            if key_expiration and key_expiration < datetime.datetime.now(
                tz=datetime.UTC
            ):
                del self[key]
                return False

            return True

        def __getitem__(self, key):
            try:
                value = super().__getitem__(key)[0]
                return value
            except KeyError:
                return None

        def __setitem__(self, key, value):
            value, ignore_ttl = value  # unpack tuple
            ttl_value = (
                (datetime.datetime.now() + self.time_to_live)
                if (self.time_to_live and not ignore_ttl)
                else None
            )  # ignore ttl if ignore_ttl is True
            super().__setitem__(key, (value, ttl_value))

    def __init__(self, time_to_live=60, maxsize=1024, skip_args: int = 0):
        """

        :param time_to_live: Use time_to_live as None for non expiring cache
        :param maxsize: Use maxsize as None for unlimited size cache
        :param skip_args: Use `1` to skip first arg of func in determining cache key
        """
        self.ttl = self._TTL(time_to_live=time_to_live, maxsize=maxsize)
        self.skip_args = skip_args

    def __call__(self, func: Callable[[Callable[..., Any]], Any]) -> Callable[..., Any]:
        async def wrapper(*args: Any, **kwargs: Any):
            key = make_key(args, kwargs)
            if key in self.ttl:
                val = self.ttl[key]
            else:
                self.ttl[key] = await func(*args, **kwargs)
                val = self.ttl[key]

            return val

        wrapper.__name__ += func.__name__

        return wrapper
