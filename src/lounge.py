from __future__ import annotations
from typing import TYPE_CHECKING, Any, Self, Literal, ParamSpec, overload
from collections.abc import Callable

from enum import Enum
import asyncio
import logging
from functools import cached_property

from pyytlounge import YtLoungeApi

from .video import CurrentVideo
from .events_handlers import WithEventsHandlers

if TYPE_CHECKING:
    from .api_helper import APIHelper
    from .types.video import Video
    from .types.events import *

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
    def from_str(cls, event_type: str) -> KnownEvents:
        try:
            return cls(event_type)
        except ValueError:
            return cls.UNKNWON

    @overload
    def cast_data(  # type: ignore
        cls: Literal[KnownEvents.NOW_PLAYING],  # type: ignore
        data: Any,
    ) -> NowPlaying: ...

    @overload
    def cast_data(
        cls: Literal[KnownEvents.AD_STATE_CHANGE],  # type: ignore
        data: Any,
    ) -> dict[str, Any]: ...

    @overload
    def cast_data(
        cls: Literal[KnownEvents.VOLUME_CHANGED],  # type: ignore
        data: Any,
    ) -> VolumeChanged: ...

    @overload
    def cast_data(
        cls: Literal[KnownEvents.AD_PLAYING],  # type: ignore
        data: Any,
    ) -> dict[str, Any]: ...

    @overload
    def cast_data(
        cls: Literal[KnownEvents.LOUNGE_STATUS],  # type: ignore
        data: Any,
    ) -> LoungeStatus: ...

    @overload
    def cast_data(
        cls: Literal[KnownEvents.SUBTITLES_TRACK_CHANGED],  # type: ignore
        data: Any,
    ) -> VideoData: ...

    @overload
    def cast_data(
        cls: Literal[KnownEvents.LOUNGE_SCREEN_DISCONNECTED],  # type: ignore
        data: Any,
    ) -> dict[str, Any]: ...

    @overload
    def cast_data(
        cls: Literal[KnownEvents.AUTOPLAY_MODE_CHANGED],  # type: ignore
        data: Any,
    ) -> dict[str, Any]: ...
    @overload
    def cast_data(
        cls: Literal[KnownEvents.AUTOPLAY_UP_NEXT],  # type: ignore
        data: Any,
    ) -> dict[str, Any]: ...
    @overload
    def cast_data(
        cls: Literal[KnownEvents.STATE_CHANGE],  # type: ignore
        data: Any,
    ) -> OnStateChange: ...

    @classmethod
    def cast_data(
        cls: type[Self],
        data: Any,
    ) -> KnownEventPayload | dict[str, Any]:
        return data


P = ParamSpec("P")


def always_take_data(func: Callable[..., Any] | Callable[[], Any]) -> Any:
    def wrapper(data: KnownEventPayload) -> Any:
        # print("wrapper: ", data, func)
        try:
            return func(data)  # type: ignore
        except TypeError:
            try:
                return func()  # type: ignore
            except TypeError:
                return func(data)  # type: ignore

    return wrapper


class LoungeAPI(YtLoungeApi, WithEventsHandlers):
    def __init__(
        self,
        api_helper: APIHelper,
    ) -> None:
        self.device_name: str = api_helper.config.device_name
        super().__init__(
            device_name=self.device_name,
            logger=self.logger,
        )
        WithEventsHandlers.__init__(self)

        # use our own session and connector
        web_session = api_helper.web_session
        self.conn = web_session.connector
        self.web_session = web_session

        self.api_helper: APIHelper = api_helper
        self.volume_state: VolumeChanged = {
            "volume": "100",
            "muted": "false",
        }
        self.paused: bool = False
        self.subscribe_task: asyncio.Task | None = None
        self.subscribe_task_watchdog: asyncio.Task | None = None
        self.callback: Any = None  # type: ignore

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

    @cached_property
    def logger(self) -> Any:
        return logging.getLogger(f"iSponsorBlockTV-{self.device_name!r}")

    # # Ensures that we still are subscribed to the lounge
    async def _watchdog(self):
        await asyncio.sleep(
            35
        )  # YouTube sends at least a message every 30 seconds (no-op or any other)
        if self.subscribe_task:
            try:
                self.subscribe_task.cancel()
            except Exception as e:
                self.logger.exception("Error cancelling subscribe task.", exc_info=e)

    # Subscribe to the lounge and start the watchdog
    async def subscribe_monitored(self, callback: Callable) -> asyncio.Task[Any]:
        self.callback: Callable = callback
        try:
            self.restart_watchdog()
        except Exception:  # noqa: BLE001, S110
            pass  # No watchdog task
        finally:
            self.subscribe_task = self.api_helper.create_task(
                super().subscribe(callback)
            )

        return self.subscribe_task

    def restart_watchdog(self) -> None:
        # (Re)start the watchdog
        # A bunch of events useful to detect ads playing, and the next video before it starts playing (that way we
        # can get the segments)
        try:
            self.subscribe_task_watchdog.cancel()  # type: ignore
        except:  # noqa: S110
            pass
        finally:
            self.subscribe_task_watchdog = self.api_helper.create_task(self._watchdog())

    async def update_current_video_data(self) -> None:
        video_id = self.current_video.video_id if self.current_video else None
        if not video_id:
            return

        self.current_video_data = await self.api_helper.get_video_from_id(video_id)

    # Process a lounge subscription event
    def _process_event(
        self, event_type: KnownEvents | str, args: list[KnownEventPayload]
    ) -> None:
        # print(f"process_event({event_type}, {args})")
        self.logger.debug(f"process_event({event_type}, {args})")
        self.restart_watchdog()

        event = KnownEvents.from_str(event_type)  # type: ignore
        if event is KnownEvents.UNKNWON:
            self.logger.debug(f"Unknown event type: {event_type}")
            super()._process_event(event_type, args)  # type: ignore
            return

        data = event.cast_data(args[0] if args else {})

        # print("event: ", event, "data: ", data, "args: ", args)

        # if event is KnownEvents.SUBTITLES_TRACK_CHANGED:
        # self.shorts_disconnected = True
        #  return

        if event in (KnownEvents.NOW_PLAYING, KnownEvents.STATE_CHANGE):
            data = event.cast_data(data)
            if len(data) == 1 and "listId" in data:  # Partial data
                return  # Nothing to do

            # handle partial above
            _data: NowPlaying | OnStateChange = data  # type: ignore

            state = _data.get("state", "")
            # print("state: ", state)
            if state == "2":
                self.paused = True
            elif state in ("-1", "1"):
                self.paused = False

            video_id: str = data.get("videoId", "")
            if data:
                if self.current_video:
                    self.current_video._update(_data)
                else:
                    self.current_video = CurrentVideo(_data)

                self.api_helper.create_task(self.update_current_video_data())
            else:
                self.current_video = None
                self.current_video_data = None

            self.api_helper.create_task(
                self.api_helper.send_current_video_webhook(self, video_id)
            )

        try:
            self.event_to_handler[event](data)  # type: ignore
        except Exception as e:
            self.logger.exception(f"Error processing event {event_type}.", exc_info=e)

        super()._process_event(event_type, args)  # type: ignore

    # Test to wrap the command function in a mutex to avoid race conditions with
    # the _command_offset (TODO: move to upstream if it works)
    async def _command(self, command: str, command_parameters: dict[Any, Any] | None = None) -> bool:  # type: ignore
        async with self._command_mutex:
            return await super()._command(command, command_parameters)  # type: ignore

    # Set the volume to a specific value (0-100)
    async def set_volume(self, volume: int) -> bool:
        return await self._command("setVolume", {"volume": volume})

    # Mute or unmute the device (if the device already is in the desired state, nothing happens)
    # mute: True to mute, False to unmute
    # override: If True, the command is sent even if the device already is in the desired state
    # TODO: Only works if the device is subscribed to the lounge
    async def mute(self, mute: bool, override: bool = False) -> None:
        mute_str = "true" if mute else "false"
        if override or self.volume_state.get("muted", "false") != mute_str:
            self.volume_state["muted"] = mute_str
            # YouTube wants the volume when unmuting, so we send it
            await self._command(
                "setVolume",
                {"volume": self.volume_state.get("volume", 100), "muted": mute_str},
            )

    async def set_auto_play_mode(self, enabled: bool) -> None:
        await self._command(
            "setAutoplayMode", {"autoplayMode": "ENABLED" if enabled else "DISABLED"}
        )

    async def play_video(self, video_id: str) -> bool:
        return await self._command("setPlaylist", {"videoId": video_id})

    async def close(self) -> None:
        if self.subscribe_task:
            try:
                self.subscribe_task.cancel()
            except Exception:  # noqa: BLE001, S110
                pass

        if self.subscribe_task_watchdog:
            try:
                self.subscribe_task_watchdog.cancel()
            except Exception:  # noqa: BLE001, S110
                pass

        try:
            self._command_mutex.release()
        except Exception:  # noqa: BLE001, S110
            pass

        # await self.disconnect()
        self._connection_lost()
        self.auth.lounge_id_token = None  # type: ignore
        self.auth.screen_id = None  # type: ignore
        self.current_video = None
        await super().close()
