from __future__ import annotations
from typing import TYPE_CHECKING, Any, TypedDict

import json
import pathlib

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
    discord_bot_token: str


class Config:
    _instance: Config | None = None

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
        "discord_bot_token",
        "_data",
    )

    def __new__(cls, path: str | pathlib.Path) -> Config:
        if cls._instance is None:
            cls._instance = super().__new__(cls)

        return cls._instance

    def __init__(self, path: str | pathlib.Path) -> None:
        if isinstance(path, str):
            path = pathlib.Path(path)

        self.path: pathlib.Path = path
        self._update()

    def _asdict(self) -> ConfigPayload:
        data: ConfigPayload = {}  # type: ignore
        for key in self.__slots__:
            if key in ("path", "_data"):
                continue

            if key == "devices":
                data[key] = [d._asdict() for d in self.devices]
            else:
                data[key] = getattr(self, key)

        print("Data", data)
        return data

    @property
    def data(self) -> ConfigPayload:
        return self._asdict()

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
        self.discord_bot_token = data.get("discord_bot_token", "")

        if not self.devices:
            msg = "No devices found, please add at least one device"
            raise RuntimeError(msg)

        if not self.apikey and self.channel_whitelist:
            msg = "No youtube API key found and channel whitelist is not empty"
            raise ValueError(msg)

    def save(self) -> None:
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(self._asdict(), file, indent=4)

        self._update()

    def append_device(self, device: DeviceConfig) -> None:
        self.devices.append(Device(device))

    def remove_device(self, screen_id: str) -> None:
        for device in self.devices:
            if device.screen_id == screen_id:
                self.devices.remove(device)
                break

    def add_device(
        self,
        screen_id: str,
        name: str,
        offset: int | None = None,
    ) -> None:
        device: DeviceConfig = {
            "screen_id": screen_id,
            "name": name,
            "offset": offset or 0,
        }
        self.append_device(device)

    def __eq__(self, other: Config) -> bool:
        if isinstance(other, Config):
            return self._data == other._data
        raise NotImplementedError
