from __future__ import annotations
from typing import TYPE_CHECKING, Any, Self, ParamSpec
from collections.abc import Callable

from enum import Enum
import asyncio
import logging
from functools import cached_property

from pyytlounge import YtLoungeApi
from async_utils.task_cache import lrutaskcache

from .video import CurrentVideo
from .events_handlers import WithEventsHandlers

if TYPE_CHECKING:
    from .api_helper import APIHelper, ProcessedSegment
    from ._types.video import Video
    from ._types.events import *

__all__ = ("LoungeAPI",)


class KnownEvents(Enum):
    UNKNWON = "unknown"
    STATE_CHANGE = "onStateChange"
    NOW_PLAYING = "nowPlaying"
    AD_STATE_CHANGE = "onAdStateChange"
    AUTOPLAY_UP_NEXT = "autoplayUpNext"
    VOLUME_CHANGED = "volumeChanged"
    AD_PLAYING = "adPlaying"
    LOUNGE_STATUS = "loungeStatus"
    SUBTITLES_TRACK_CHANGED = "onSubtitlesTrackChanged"
    LOUNGE_SCREEN_DISCONNECTED = "loungeScreenDisconnected"
    AUTOPLAY_MODE_CHANGED = "onAutoplayModeChanged"

    @classmethod
    def from_str(cls, event_type: str | Self | KnownEventsStr) -> KnownEvents:
        try:
            return cls(event_type)
        except ValueError:
            return cls.UNKNWON

    @classmethod
    def cast_data(cls, data: Any) -> KnownEventPayload | dict[str, Any]:
        return data


P = ParamSpec("P")


def always_take_data(func: Callable[..., Any]) -> Callable[[KnownEventPayload], Any]:
    def wrapper(data: KnownEventPayload) -> Any:
        try:
            return func(data)
        except TypeError:
            return func()

    return wrapper


class LoungeAPI(YtLoungeApi, WithEventsHandlers):
    def __init__(self, api_helper: APIHelper) -> None:
        self.device_name: str = api_helper.config.device_name
        super().__init__(device_name=self.device_name, logger=self.logger)
        WithEventsHandlers.__init__(self)

        self.api_helper: APIHelper = api_helper
        self.volume_state: VolumeChanged = {"volume": "100", "muted": "false"}
        self.paused: bool = False
        self.subscribe_task: asyncio.Task[Any] | None = None
        self.subscribe_task_watchdog: asyncio.Task[Any] | None = None
        self.shorts_disconnected: bool = False
        self.waiting_for_shorts: bool = False
        self._command_mutex: asyncio.Lock = asyncio.Lock()
        self.current_video: CurrentVideo | None = None
        self.current_video_data: Video | None = None

        self.event_to_handler: dict[KnownEvents, Callable[[KnownEventPayload], Any]] = {
            KnownEvents.STATE_CHANGE: always_take_data(self._handle_state_change),
            KnownEvents.NOW_PLAYING: always_take_data(self._handle_now_playing),
            KnownEvents.AD_STATE_CHANGE: always_take_data(
                self._handle_add_state_change
            ),
            KnownEvents.VOLUME_CHANGED: always_take_data(self._handle_volume_changed),
            KnownEvents.AUTOPLAY_UP_NEXT: always_take_data(
                self._handle_autoplay_up_next
            ),
            KnownEvents.AD_PLAYING: always_take_data(self._handle_ad_playing),
            KnownEvents.LOUNGE_STATUS: always_take_data(self._handle_lounge_status),
            KnownEvents.SUBTITLES_TRACK_CHANGED: always_take_data(
                self._handle_subtitles_track_changed
            ),
            KnownEvents.LOUNGE_SCREEN_DISCONNECTED: always_take_data(
                self._handle_lounge_screen_disconnected
            ),
            KnownEvents.AUTOPLAY_MODE_CHANGED: always_take_data(
                self._handle_autoplay_mode_changed
            ),
        }
        self.conn = (
            self.api_helper.web_session.connector
        )  # pyright: ignore[reportAttributeAccessIssue]
        self.session = self.api_helper.web_session

    async def __aenter__(self) -> Self:
        return self

    @cached_property
    def logger(self) -> logging.Logger:
        return logging.getLogger(f"iSponsorBlockTV-{self.device_name!r}")

    async def _watchdog(self) -> None:
        await asyncio.sleep(35)
        if self.subscribe_task:
            self.subscribe_task.cancel()

    async def subscribe_monitored(
        self, callback: Callable[..., Any]
    ) -> asyncio.Task[Any]:
        self.callback = callback
        self.restart_watchdog()
        self.subscribe_task = self.api_helper.create_task(super().subscribe(callback))
        return self.subscribe_task

    def restart_watchdog(self) -> None:
        if self.subscribe_task_watchdog:
            self.subscribe_task_watchdog.cancel()
        self.subscribe_task_watchdog = self.api_helper.create_task(self._watchdog())

    async def update_current_video_data(self) -> None:
        if self.current_video and self.current_video.video_id:
            self.current_video_data = await self.api_helper.get_video_from_id(
                self.current_video.video_id
            )

    @lrutaskcache(ttl=300, maxsize=50, cache_transform=lambda args, _: (args[1], {}))
    async def get_segments(self, video_id: str) -> list[ProcessedSegment]:
        print("Getting segments for video with ID %s", video_id)
        if await self.api_helper.is_whitelisted(video_id):
            self.logger.info(
                "Channel is whitelisted, skipping segments for video with ID %s",
                video_id,
            )
            return []
        return await self.api_helper.segments_handler.get_segments(
            video_id=video_id,
            minimal_skip_length=self.api_helper.config.minimum_skip_length,
        )

    def _process_event(
        self, event_type: KnownEvents | str, args: list[KnownEventPayload]
    ) -> None:
        self.logger.debug("process_event(%s, %s)", event_type, args)
        self.restart_watchdog()

        event = KnownEvents.from_str(event_type)
        if event is KnownEvents.UNKNWON:
            self.logger.debug("Unknown event type: %s", event_type)
            super()._process_event(str(event_type), args)
            return

        data = event.cast_data(args[0] if args else {})

        if event in {KnownEvents.NOW_PLAYING, KnownEvents.STATE_CHANGE}:
            data = event.cast_data(data)
            if len(data) == 1 and "listId" in data:
                return

            state = data.get("state", "")
            self.paused = state == "2"

            if data:
                if self.current_video:
                    self.current_video._update(
                        data  # pyright: ignore[reportArgumentType]
                    )
                else:
                    self.current_video = CurrentVideo(
                        data  # pyright: ignore[reportArgumentType]
                    )
                self.api_helper.create_task(self.update_current_video_data())
            else:
                self.current_video = None
                self.current_video_data = None

        try:
            self.event_to_handler[event](data)  # pyright: ignore[reportArgumentType]
        except Exception as e:
            self.logger.exception("Error processing event %s.", event_type, exc_info=e)

        super()._process_event(str(event_type), args)

    async def _command(
        self, command: str, command_parameters: dict[Any, Any] | None = None
    ) -> bool:
        async with self._command_mutex:
            return await super()._command(  # pyright: ignore[reportArgumentType, reportUnknownMemberType]
                command,
                command_parameters,  # pyright: ignore[reportArgumentType, reportUnknownMemberType]
            )

    async def set_volume(self, volume: int) -> bool:
        return await self._command("setVolume", {"volume": volume})

    async def mute(self, mute: bool, override: bool = False) -> None:  # noqa: FBT001
        mute_str = "true" if mute else "false"
        if override or self.volume_state.get("muted", "false") != mute_str:
            self.volume_state["muted"] = mute_str
            await self._command(
                "setVolume",
                {"volume": self.volume_state.get("volume", 100), "muted": mute_str},
            )

    async def set_auto_play_mode(self, enabled: bool) -> None:  # noqa: FBT001
        await self._command(
            "setAutoplayMode", {"autoplayMode": "ENABLED" if enabled else "DISABLED"}
        )

    async def play_video(self, video_id: str) -> bool:
        return await self._command("setPlaylist", {"videoId": video_id})

    async def close(self) -> None:
        if self.subscribe_task:
            self.subscribe_task.cancel()
        if self.subscribe_task_watchdog:
            self.subscribe_task_watchdog.cancel()
        try:
            self._command_mutex.release()
        except Exception:  # noqa: BLE001, S110
            pass
        self._connection_lost()
        self.auth.lounge_id_token = None  # pyright: ignore[reportAttributeAccessIssue]
        self.auth.screen_id = None  # pyright: ignore[reportAttributeAccessIssue]
        self.current_video = None
        await super().close()
