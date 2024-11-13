from __future__ import annotations

import json
import pathlib
from typing import TYPE_CHECKING, Any, TypedDict

from .device_manager import Device

if TYPE_CHECKING:
    from .device_manager import DeviceConfig

__all__ = ("Config",)


class ChannelConfig(TypedDict):
    id: str
    name: str

class CurrentVideoWebhook(TypedDict):
    id: int
    channel_id: int
    token: str

class ConfigPayload(TypedDict):
    devices: list[DeviceConfig]
    apikey: str
    skip_categories: list[str]
    channel_whitelist: list[ChannelConfig]
    skip_count_tracking: bool
    mute_ads: bool
    skip_ads: bool
    autoplay: bool
    handle_shorts: bool
    device_name: str
    minimum_skip_length: int
    current_video_webhook: CurrentVideoWebhook


class Config:
    __slots__ = (
        "devices",
        "apikey",
        "skip_categories",
        "channel_whitelist",
        "skip_count_tracking",
        "mute_ads",
        "skip_ads",
        "autoplay",
        "handle_shorts",
        "device_name",
        "minimum_skip_length",
        "path",
        "current_video_webhook",
        "_data",
    )

    def __init__(self, path: str | pathlib.Path) -> None:
        if isinstance(path, str):
            path = pathlib.Path(path)

        self.path: pathlib.Path = path
        self._data: ConfigPayload = {}  # type: ignore
        self._update()

        if not self._data:
            msg = "Config file is empty"
            raise ValueError(msg)
        
        
    def _update(
        self,
    ) -> None:
        with self.path.open("r", encoding="utf-8") as file:
            data: ConfigPayload = json.load(file)

        self.devices = [Device(d) for d in data.get("devices", [])]
        self.apikey = data.get("apikey", "")
        self.skip_categories = data.get("skip_categories", ["sponsor"])
        self.channel_whitelist = data.get("channel_whitelist", [])
        self.skip_count_tracking = data.get("skip_count_tracking", True)
        self.mute_ads = data.get("mute_ads", False)
        self.skip_ads = data.get("skip_ads", False)
        self.autoplay = data.get("autoplay", False)
        self.handle_shorts = data.get("handle_shorts", True)
        self.device_name = data.get("device_name", "iSponsorBlockTV")
        self.minimum_skip_length = data.get("minimum_skip_length", 0)
        self.current_video_webhook = data.get("current_video_webhook", {})

        if not self.devices:
            msg = "No devices found, please add at least one device"
            raise RuntimeError(msg)

        if not self.apikey and self.channel_whitelist:
            msg = "No youtube API key found and channel whitelist is not empty"
            raise ValueError(msg)

        self._data: ConfigPayload = data

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(self._data, file, indent=4)

    def __eq__(self, other: Config) -> bool:
        if isinstance(other, Config):
            return self._data == other._data
        raise NotImplementedError

    def __setattr__(self, name: str, value: Any) -> None:
        if name in (
            "_data",
            "path",
        ):
            super().__setattr__(name, value)
            return

        super().__setattr__(name, value)
        self._data[name] = value
