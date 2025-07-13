from __future__ import annotations
from typing import TYPE_CHECKING, Any, Self, ParamSpec
from collections.abc import Callable

from enum import Enum
import sys
import time
import asyncio
import logging
from functools import cached_property
from uuid import uuid4
import inspect

from pyytlounge import YtLoungeApi
from async_utils.task_cache import lrutaskcache
from pyytlounge.exceptions import NotLinkedException
from pyytlounge.util import as_aiter
from pyytlounge.wrapper import api_base

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
        if inspect.signature(func).parameters:
            return func(data)
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
        self.watchdog_running = False
        self.last_event_time = 0

        self.event_to_handler: dict[KnownEvents, Callable[[KnownEventPayload], Any]] = {
            KnownEvents.STATE_CHANGE: always_take_data(self._handle_state_change),
            KnownEvents.NOW_PLAYING: always_take_data(self._handle_now_playing),
            KnownEvents.AD_STATE_CHANGE: always_take_data(self._handle_add_state_change),
            KnownEvents.VOLUME_CHANGED: always_take_data(self._handle_volume_changed),
            KnownEvents.AUTOPLAY_UP_NEXT: always_take_data(self._handle_autoplay_up_next),
            KnownEvents.AD_PLAYING: always_take_data(self._handle_ad_playing),
            KnownEvents.LOUNGE_STATUS: always_take_data(self._handle_lounge_status),
            KnownEvents.SUBTITLES_TRACK_CHANGED: always_take_data(self._handle_subtitles_track_changed),
            KnownEvents.LOUNGE_SCREEN_DISCONNECTED: always_take_data(self._handle_lounge_screen_disconnected),
            KnownEvents.AUTOPLAY_MODE_CHANGED: always_take_data(self._handle_autoplay_mode_changed),
        }
        self.conn = self.api_helper.web_session.connector  # pyright: ignore[reportAttributeAccessIssue]
        self.session = self.api_helper.web_session

    async def __aenter__(self) -> Self:
        return self

    @cached_property
    def logger(self) -> logging.Logger:
        return logging.getLogger(f"iSponsorBlockTV-{self.device_name!r}")

    # Ensures that we still are subscribed to the lounge
    async def _watchdog(self):
        self.watchdog_running = True
        self.last_event_time = asyncio.get_event_loop().time()

        try:
            while self.watchdog_running:
                await asyncio.sleep(10)
                current_time = asyncio.get_event_loop().time()
                time_since_last_event = current_time - self.last_event_time

                # YouTube sends a message at least every 30 seconds
                if time_since_last_event > 60:
                    self.logger.debug(f"Watchdog triggered: No events for {time_since_last_event:.1f} seconds")

                    # Cancel current subscription
                    if self.subscribe_task and not self.subscribe_task.done():
                        self.subscribe_task.cancel()
                        await asyncio.sleep(1)  # Give it time to cancel
        except asyncio.CancelledError:
            self.logger.debug("Watchdog task cancelled")
            self.watchdog_running = False
        except BaseException as e:
            self.logger.error(f"Watchdog error: {e}")
            self.watchdog_running = False

    # Subscribe to the lounge and start the watchdog
    async def subscribe_monitored(self, callback):
        self.callback = callback

        # Stop existing watchdog if running
        if self.subscribe_task_watchdog and not self.subscribe_task_watchdog.done():
            self.watchdog_running = False
            self.subscribe_task_watchdog.cancel()
            try:
                await self.subscribe_task_watchdog
            except (asyncio.CancelledError, Exception):
                pass

        # Start new subscription
        if self.subscribe_task and not self.subscribe_task.done():
            self.subscribe_task.cancel()
            try:
                await self.subscribe_task
            except (asyncio.CancelledError, Exception):
                pass

        self.subscribe_task = asyncio.create_task(super().subscribe(callback))
        self.subscribe_task_watchdog = asyncio.create_task(self._watchdog())
        return self.subscribe_task

    async def update_current_video_data(self) -> None:
        if self.current_video and self.current_video.video_id:
            self.current_video_data = await self.api_helper.get_video_from_id(self.current_video.video_id)

    @lrutaskcache(ttl=300, maxsize=50, cache_transform=lambda args, _: (args[1], {}))
    async def get_segments(self, video_id: str) -> list[ProcessedSegment]:
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

    def _process_event(self, event_type: str, args: list[Any]):
        self.logger.debug(f"process_event({event_type}, {args})")  # noqa: G004
        # Update last event time for the watchdog
        self.last_event_time = time.time()

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

    # Set the volume to a specific value (0-100)
    async def set_volume(self, volume: int) -> None:
        await self._command("setVolume", {"volume": volume})

    async def mute(self, mute: bool, override: bool = False) -> None:
        mute_str = "true" if mute else "false"
        if override or self.volume_state.get("muted", "false") != mute_str:
            self.volume_state["muted"] = mute_str
            # YouTube wants the volume when unmuting, so we send it
            await self._command(
                "setVolume",
                {"volume": self.volume_state.get("volume", 100), "muted": mute_str},
            )

    async def play_video(self, video_id: str) -> bool:
        return await self._command("setPlaylist", {"videoId": video_id})

    async def get_now_playing(self) -> bool:
        return await self._command("getNowPlaying")

    # Test to wrap the command function in a mutex to avoid race conditions with
    # the _command_offset (TODO: move to upstream if it works)
    async def _command(self, command: str, command_parameters: dict[str, Any] | None = None) -> bool:
        async with self._command_mutex:
            return await super()._command(command, command_parameters)  # pyright: ignore[reportUnknownMemberType, reportArgumentType]

    def _common_connection_parameters(self) -> dict[str, Any]:
        return {
            "name": self.device_name,
            "loungeIdToken": self.auth.lounge_id_token,
            "SID": self._sid,  # type: ignore  # noqa: PGH003
            "AID": self._last_event_id,  # type: ignore  # noqa: PGH003
            "gsessionid": self._gsession,  # type: ignore  # noqa: PGH003
            "device": "REMOTE_CONTROL",
            "app": "ytios-phone-20.15.1",
            "VER": "8",
            "v": "2",
        }

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

    async def connect(self) -> bool:
        """Attempt to connect using the previously set tokens"""
        if not self.linked():
            raise NotLinkedException("Not linked")

        connect_body = {
            "id": self.auth.screen_id,
            "mdx-version": "3",
            "TYPE": "xmlhttp",
            "theme": "cl",
            "sessionSource": "MDX_SESSION_SOURCE_UNKNOWN",
            "connectParams": '{"setStatesParams": "{"playbackSpeed":0}"}',
            "RID": "1",
            "CVER": "1",
            "capabilities": "que,dsdtr,atp,vsp",
            "ui": "false",
            "app": "ytios-phone-20.15.1",
            "pairing_type": "manual",
            "VER": "8",
            "loungeIdToken": self.auth.lounge_id_token,
            "device": "REMOTE_CONTROL",
            "name": self.device_name,
        }
        connect_url = f"{api_base}/bc/bind"
        assert self.session is not None, "Session must be set before connecting"
        async with self.session.post(url=connect_url, data=connect_body) as resp:
            try:
                text = await resp.text()
                if resp.status == 401:
                    if "Connection denied" in text:
                        self._logger.warning("Connection denied, attempting to circumvent the issue")
                        await self.connect_as_screen()
                    # self._lounge_token_expired()
                    return False

                if resp.status != 200:
                    self._logger.warning("Unknown reply to connect %i %s", resp.status, resp.reason)
                    return False
                lines = text.splitlines()
                async for events in self._parse_event_chunks(as_aiter(lines)):
                    self._process_events(events)
                self._command_offset = 1
                return self.connected()
            except:
                self._logger.exception(
                    "Handle connect failed, status %s reason %s",
                    resp.status,
                    resp.reason,
                )
                raise

    async def connect_as_screen(self) -> bool:
        if not self.linked():
            msg = "Not linked"
            raise NotLinkedException(msg)

        connect_body = {
            "id": str(uuid4()),
            "mdx-version": "3",
            "TYPE": "xmlhttp",
            "theme": "cl",
            "sessionSource": "MDX_SESSION_SOURCE_UNKNOWN",
            "connectParams": '{"setStatesParams": "{"playbackSpeed":0}"}',
            "sessionNonce": str(uuid4()),
            "RID": "1",
            "CVER": "1",
            "capabilities": "que,dsdtr,atp,vsp",
            "ui": "false",
            "app": "ytios-phone-20.15.1",
            "pairing_type": "manual",
            "VER": "8",
            "loungeIdToken": self.auth.lounge_id_token,
            "device": "LOUNGE_SCREEN",
            "name": self.device_name,
        }
        connect_url = f"{api_base}/bc/bind"
        assert self.session is not None, "Session must be set before connecting"
        async with self.session.post(url=connect_url, data=connect_body) as resp:
            try:
                await resp.text()
                self.logger.error(
                    "Connected as screen: please force close the app on the device for iSponsorBlockTV to work properly"
                )
                self.logger.warning("Exiting in 5 seconds")
                await asyncio.sleep(5)
                sys.exit(0)
            except:
                self._logger.exception(
                    "Handle connect failed, status %s reason %s",
                    resp.status,
                    resp.reason,
                )
                raise
