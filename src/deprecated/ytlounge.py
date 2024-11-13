from __future__ import annotations

import asyncio
import contextlib
from enum import Enum
import json
import logging
import re
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NotRequired,
    TypedDict,
)


import pyytlounge

from .constants import youtube_client_blacklist
from datetime import datetime, timedelta
import time

if TYPE_CHECKING:
    ...

class DeviceInfo(TypedDict):
    brand: str
    model: str
    year: int
    os: str
    osVersion: str
    chipset: str
    clientName: str
    dialAdditionalDataSupportLevel: Literal["full", "none", "partial"]
    mdxDialServerType: Literal[
        "MDX_DIAL_SERVER_TYPE_IN_APP", "MDX_DIAL_SERVER_TYPE_EXTERNAL"
    ]


class Device(TypedDict):
    app: str
    capabilities: str
    clientName: str
    experiments: str
    name: str
    theme: str
    id: str
    type: str
    hasCc: NotRequired[str]
    deviceInfo: NotRequired[str] # DeviceInfo
    receiverIdentityMatchStatus: str
    pairingType: NotRequired[str]
    deviceContext: NotRequired[str]
    localChannelEncryptionKey: NotRequired[str]


class LoungeStatus(TypedDict):
    queueId: str
    devices: str  # List[Device]


class SubtitleStyle(TypedDict):
    background: str
    backgroundOpacity: float
    charEdgeStyle: str
    color: str
    fontFamily: int
    fontSizeIncrement: int
    fontStyle: int
    textOpacity: float
    windowColor: str
    windowOpacity: float
    backgroundOverride: bool
    backgroundOpacityOverride: bool
    charEdgeStyleOverride: bool
    colorOverride: bool
    fontFamilyOverride: bool
    fontSizeIncrementOverride: bool
    textOpacityOverride: bool
    windowColorOverride: bool
    windowOpacityOverride: bool
    fontFamilyOption: str


class VideoData(TypedDict):
    videoId: str
    style: SubtitleStyle


class OnStateChange(TypedDict):
    currentTime: str
    duration: str
    cpn: str
    loadedTime: str
    state: Literal["0", "1", "2", "3"]
    seekableStartTime: str
    seekableEndTime: str


class PartialNotPlaying(TypedDict):
    listId: str


class NowPlaying(PartialNotPlaying):
    duration: str
    currentTime: str
    cpn: str
    loadedTime: str
    videoId: str
    state: str
    params: str
    seekableEndTime: str
    seekableStartTime: str


class VolumeChanged(TypedDict):
    volume: str
    muted: str


class OAutoplayModeChanged(TypedDict):
    autoplayMode: Literal["ENABLED", "DISABLED"]


class OnHasPreviousNextChanged(TypedDict):
    hasPrevious: Literal["true", "false"]
    hasNext: Literal["true", "false"]


class PlaylistModified(TypedDict):
    listId: str
    firstVideoId: str


class VideoState(Enum):
    START_PLAYING = "-1"  # ?
    STOPPED = "0"
    BUFFERING = "3"  # ?
    PAUSED = "2"
    PLAYING = "1"


KnownEvents = Literal[
    "onStateChange",
    "nowPlaying",
    "onAdStateChange",
    "onVolumeChanged",
    "onAutoplayModeChanged",
    "onSubtitlesTrackChanged",
    "loungeScreenDisconnected",
    "loungeStatus",
    "autoplayUpNext",
    "adPlaying",
]

KnownEventPayload = (
    NowPlaying
    | OnStateChange
    | PartialNotPlaying
    | VolumeChanged
    | OAutoplayModeChanged
    | OnHasPreviousNextChanged
    | PlaylistModified
    | LoungeStatus
    | VideoData
)


class CurrentVideo:
    def __init__(
        self,
        data: NowPlaying | OnStateChange,
    ) -> None:
        self._update(data)

    def __repr__(self) -> str:
        return (
            f"<CurrentVideo video_id={self.video_id} state={self.state.name}"
            f" current_time={self.current_time_str} duration={self.duration_str}>"
        )

    def _update(self, data: NowPlaying | OnStateChange) -> None:
        self.data = data
        if "videoId" in data:
            self.video_id = data["videoId"]

        self.current_time: float = float(data["currentTime"])
        self.duration: float = float(data["duration"])
        self.loaded_time: float = float(data["loadedTime"])
        self.state: VideoState = VideoState(data["state"])
        self.seekable_start_time: float = float(data["seekableStartTime"])
        self.seekable_end_time: float = float(data["seekableEndTime"])

        self.dt_current_time = datetime(1970, 1, 1) + timedelta(
            seconds=self.current_time
        )
        self.dt_duration = datetime(1970, 1, 1) + timedelta(seconds=self.duration)
        self.dt_seekable_start_time = datetime(1970, 1, 1) + timedelta(
            seconds=self.seekable_start_time
        )
        self.dt_seekable_end_time = datetime(1970, 1, 1) + timedelta(
            seconds=self.seekable_end_time
        )

    def format_time(self, seconds: float) -> str:
        hours, remainder = divmod(seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        milliseconds = int((seconds - int(seconds)) * 1000)
        seconds = int(seconds)

        if hours > 0:
            return (
                f"{int(hours)}:{int(minutes):02}:{seconds:02}.{milliseconds:03}".rstrip(
                    "0"
                ).rstrip(".")
            )
        elif minutes > 0:
            return f"{int(minutes)}:{seconds:02}.{milliseconds:03}".rstrip("0").rstrip(
                "."
            )
        else:
            return f"{seconds}.{milliseconds:03}".rstrip("0").rstrip(".")

    def to_struct_time(self, seconds: float) -> time.struct_time:
        return time.gmtime(seconds)

    @property
    def remaining_time(self) -> str:
        return self.format_time(self.duration - self.current_time)

    @property
    def remaining_time_using_dt(self) -> str:
        return str(self.dt_duration - self.dt_current_time)

    @property
    def current_time_using_dt(self) -> str:
        return str(self.dt_current_time)

    @property
    def current_time_str(self) -> str:
        return self.format_time(self.current_time)

    @property
    def duration_str(self) -> str:
        return self.format_time(self.duration)

    @property
    def seekable_start_time_str(self) -> str:
        return self.format_time(self.seekable_start_time)

    @property
    def seekable_end_time_str(self) -> str:
        return self.format_time(self.seekable_end_time)

    @property
    def loaded_time_str(self) -> str:
        return self.format_time(self.loaded_time)


class YtLoungeApi(pyytlounge.YtLoungeApi):
    def __init__(
        self,
        config=None,
        api_helper=None,
        logger=None,
        web_session=None,
    ):
        super().__init__(config.device_name if config else "iSponsorBlockTV")
        if web_session is not None:
            print("Using the web session we passed", web_session, web_session.connector)
            self.conn = web_session.connector
            self.session = web_session  # And use the one we passed

        self.api_helper = api_helper
        self.volume_state = {}
        self.subscribe_task = None
        self.subscribe_task_watchdog = None
        self.callback = None
        self.logger = logger or logging.getLogger(__name__)
        self.shorts_disconnected = False
        self.wait_for_short_to_end: bool = False
        if config:
            self.mute_ads = config.mute_ads
            self.skip_ads = config.skip_ads
            self.autoplay = config.autoplay
            self.handle_shorts = config.handle_shorts

        self.tasks: set[asyncio.Task[Any]] = set()
        self.current_video: CurrentVideo | None = None

        self._command_mutex = asyncio.Lock()

    def create_task(self, coro):
        try:
            task = self.create_task(coro)
            task.add_done_callback(lambda fut: self.tasks.discard(fut))
        except Exception:
            return
        self.tasks.add(task)
        return task

    # Ensures that we still are subscribed to the lounge
    async def _watchdog(self):
        await asyncio.sleep(
            35
        )  # YouTube sends at least a message every 30 seconds (no-op or any other)
        if self.subscribe_task:
            try:
                self.subscribe_task.cancel()
            except Exception as e:
                self.logger.error(f"Error cancelling subscribe task: {e}")
                pass

    #async def disconnect(self) -> bool:
    #    if not self.connected():
    #        return True
    #        # raise NotConnectedException("Not connected")
#
    #    return await super().disconnect()

    # Subscribe to the lounge and start the watchdog
    async def subscribe_monitored(self, callback):
        self.callback = callback
        if self.subscribe_task_watchdog:
            try:
                self.subscribe_task_watchdog.cancel()
            except:
                pass  # No watchdog task

        try:
            self.subscribe_task = self.create_task(super().subscribe(callback))
        except Exception:
            # self.logger.error(f"Error subscribing: {e}")
            pass

        self.subscribe_task_watchdog = self.create_task(self._watchdog())
        return self.subscribe_task

    # Process a lounge subscription event
    def _process_event(
        self, event_type: KnownEvents | str, args: list[KnownEventPayload]
    ) -> None:
        print("Processing event", event_type, args)
        self.logger.debug(f"process_event({event_type}, {args})")

        data: KnownEventPayload = args[0] if args else {}  # type: ignore

        if event_type in ("onStateChange", "nowPlaying"):
            _data: NowPlaying | OnStateChange | PartialNotPlaying = data  # type: ignore
            # data: NowPlaying | OnStateChange | PartialNotPlaying  # type: ignore
            if len(data) == 1 and "listId" in data:  # Partial data
                return  # Nothing to do

            # handle partial above
            _data: NowPlaying | OnStateChange = data  # type: ignore

            if data:
                if self.current_video:
                    self.current_video._update(_data)
                else:
                    self.current_video = CurrentVideo(_data)

        print("Current video", self.current_video)

        # (Re)start the watchdog
        try:
            if self.subscribe_task_watchdog:
                self.subscribe_task_watchdog.cancel()
        except:
            pass
        finally:
            self.subscribe_task_watchdog = asyncio.create_task(self._watchdog())
        # A bunch of events useful to detect ads playing, and the next video before it starts playing (that way we
        # can get the segments)
        if event_type == "onStateChange":
            _data: OnStateChange = data  # type: ignore
            # print(data)
            # Unmute when the video starts playing
            if self.mute_ads and _data["state"] == "1":
                self.create_task(self.mute(False, override=True))
        elif event_type == "nowPlaying":
            print("NWO PLAYG", args, event_type)
            _data: NowPlaying = data  # type: ignore
            # Unmute when the video starts playing
            if self.mute_ads and _data.get("state", "0") == "1":
                self.logger.info("Ad has ended, unmuting")
                self.create_task(self.mute(False, override=True))
        elif event_type == "onAdStateChange":
            _data: dict[str, str] = data # type: ignore
            if _data["adState"] == "0":  # Ad is not playing
                self.logger.info("Ad has ended, unmuting")
                self.create_task(self.mute(False, override=True))
            elif (
                self.skip_ads and _data["isSkipEnabled"] == "true"
            ):  # YouTube uses strings for booleans
                self.logger.info("Ad can be skipped, skipping")
                self.create_task(self.skip_ad())
                self.create_task(self.mute(False, override=True))
            elif (
                self.mute_ads
            ):  # Seen multiple other adStates, assuming they are all ads
                self.logger.info("Ad has started, muting")
                self.create_task(self.mute(True, override=True))
        # Manages volume, useful since YouTube wants to know the volume when unmuting (even if they already have it)
        elif event_type == "onVolumeChanged":
            _data: VolumeChanged = data  # type: ignore
            self.volume_state = _data
            pass
        # Gets segments for the next video before it starts playing
        elif event_type == "autoplayUpNext":
            _data: dict[str, str]  = data # type: ignore
            if len(args) > 0 and (
                vid_id := _data["videoId"]
            ):  # if video id is not empty
                self.logger.info(f"Getting segments for next video: {vid_id}")
                self.create_task(self.api_helper.get_segments(vid_id))

        # #Used to know if an ad is skippable or not
        elif event_type == "adPlaying":
            data: dict[str, str]  # type: ignore
            # Gets segments for the next video (after the ad) before it starts playing
            if vid_id := data["contentVideoId"]:
                self.logger.info(f"Getting segments for next video: {vid_id}")
                self.create_task(self.api_helper.get_segments(vid_id))
            elif (
                self.skip_ads and data["isSkipEnabled"] == "true"
            ):  # YouTube uses strings for booleans
                self.logger.info("Ad can be skipped, skipping")
                self.create_task(self.skip_ad())
                self.create_task(self.mute(False, override=True))
            elif (
                self.mute_ads
            ):  # Seen multiple other adStates, assuming they are all ads
                self.logger.info("Ad has started, muting")
                self.create_task(self.mute(True, override=True))

        elif event_type == "loungeStatus":
            _data: LoungeStatus = data  # type: ignore
            devices: list[Device] = json.loads(data["devices"])
            for device in devices:
                if device["type"] == "LOUNGE_SCREEN":
                    device_info: DeviceInfo = json.loads(device.get("deviceInfo", "{}"))
                    if device_info.get("clientName", "") in youtube_client_blacklist:
                        self._sid = None
                        self._gsession = None  # Force disconnect

        elif event_type == "onSubtitlesTrackChanged":
            _data: VideoData = data  # type: ignore
            if self.shorts_disconnected and self.handle_shorts:
                video_id_saved = data.get("videoId", None)
                self.shorts_disconnected = False
                self.create_task(self.play_video(video_id_saved))
        elif event_type == "loungeScreenDisconnected":
            _data: dict[str, str] = data  # type: ignore
            if _data:  # Sometimes it's empty
                if (
                    _data["reason"] == "disconnectedByUserScreenInitiated"
                ) and self.handle_shorts:  # Short playing?
                    self.shorts_disconnected = True
        elif event_type == "onAutoplayModeChanged":
            self.create_task(self.set_auto_play_mode(self.autoplay))

        super()._process_event(event_type, args)

    # Test to wrap the command function in a mutex to avoid race conditions with
    # the _command_offset (TODO: move to upstream if it works)
    async def _command(self, command: str, command_parameters: dict = None) -> bool:  # type: ignore
        async with self._command_mutex:
            return await super()._command(command, command_parameters)

    # Set the volume to a specific value (0-100)
    async def set_volume(self, volume: int) -> bool:
        return await self._command("setVolume", {"volume": volume})

    # Mute or unmute the device (if the device already is in the desired state, nothing happens)
    # mute: True to mute, False to unmute
    # override: If True, the command is sent even if the device already is in the desired state
    # TODO: Only works if the device is subscribed to the lounge
    async def mute(self, mute: bool, override: bool = False) -> None:
        if mute:
            mute_str = "true"
        else:
            mute_str = "false"
        if override or not (self.volume_state.get("muted", "false") == mute_str):
            self.volume_state["muted"] = mute_str
            # YouTube wants the volume when unmuting, so we send it
            await self._command(
                "setVolume",
                {"volume": self.volume_state.get("volume", 100), "muted": mute_str},
            )

    async def set_auto_play_mode(self, enabled: bool):
        await self._command(
            "setAutoplayMode", {"autoplayMode": "ENABLED" if enabled else "DISABLED"}
        )

    async def play_video(self, video_id: str) -> bool:
        return await self._command("setPlaylist", {"videoId": video_id})

    async def close(self):
        self._connection_lost()
        self.auth.lounge_id_token = None
        self.auth.screen_id = None
        self.tasks.clear()
        return await super().close()
