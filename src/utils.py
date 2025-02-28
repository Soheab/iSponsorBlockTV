from typing import Any
from collections.abc import Callable

from functools import wraps

import aiohttp

__all__ = ()


def list_to_tuple(function: Callable[..., Any]) -> Callable[..., tuple[Any, ...] | Any]:
    @wraps(function)
    def wrapper(*args: Any, **kwargs: Any) -> tuple[Any, ...] | Any:
        args = tuple(tuple(x) if isinstance(x, list) else x for x in args)
        kwargs = {k: tuple(v) if isinstance(v, list) else v for k, v in kwargs.items()}
        result = function(*args, **kwargs)
        return tuple(result) if isinstance(result, list) else result

    return wrapper


class EnsureSession[C: aiohttp.BaseConnector, CA: Any, CK: Any, CV: Any]:
    def __init__(
        self,
        *args: Any,
        connector_cls: type[C] | None = None,
        connector_args: tuple[CA, ...] | None = None,
        connector_kwargs: dict[CK, CV] | None = None,
        **kwargs: Any,
    ) -> None:
        self.__connector_cls: type[C] | None = connector_cls
        self.__connector_args: tuple[CA, ...] | None = connector_args
        self.__connector_kwargs: dict[CK, CV] | None = connector_kwargs

        self.__session: aiohttp.ClientSession = aiohttp.ClientSession(
            *args,
            connector=self._get_connector(),
            timeout=aiohttp.ClientTimeout(total=10, connect=5, sock_read=5),
            **kwargs,
        )

    def __getattr__(self, name: str) -> Any:
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            return object.__getattribute__(self.__session, name)

    def _get_connector(self) -> C | None:
        if self.__connector_cls is None:
            return None

        return self.__connector_cls(
            *self.__connector_args or (), **self.__connector_kwargs or {}
        )

    def reset_connector(self) -> None:
        self.__session._connector = self._get_connector()

    def request(self, *args: Any, **kwargs: Any) -> aiohttp.client._RequestContextManager:
        return aiohttp.client._RequestContextManager(self._request(*args, **kwargs))

    def get(self, *args: Any, **kwargs: Any) -> aiohttp.client._RequestContextManager:
        return self.request("GET", *args, **kwargs)

    def post(self, *args: Any, **kwargs: Any) -> aiohttp.client._RequestContextManager:
        return self.request("POST", *args, **kwargs)

    def put(self, *args: Any, **kwargs: Any) -> aiohttp.client._RequestContextManager:
        return self.request("PUT", *args, **kwargs)

    def patch(self, *args: Any, **kwargs: Any) -> aiohttp.client._RequestContextManager:
        return self.request("PATCH", *args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> aiohttp.client._RequestContextManager:
        return self.request("DELETE", *args, **kwargs)

    async def _request(self, *args: Any, **kwargs: Any) -> aiohttp.ClientResponse:
        if self.__session.closed:
            self.reset_connector()

        if "url" in kwargs:
            kwargs["str_or_url"] = kwargs.pop("url")

        try:
            return await self.__session._request(*args, **kwargs)
        except aiohttp.ClientConnectionError:
            self.reset_connector()
            return await self.__session._request(*args, **kwargs)

    async def close(self) -> None:
        return await self.__session.close()
