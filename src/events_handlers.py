from __future__ import annotations
from typing import TYPE_CHECKING, Any

import json

from .constants import youtube_client_blacklist

if TYPE_CHECKING:
    from .lounge import LoungeAPI
    from .types.events import *

__all__ = ("WithEventsHandlers",)


class WithEventsHandlers:
    def _handle_state_change(self: LoungeAPI, data: OnStateChange) -> None:  # type: ignore
        if self.api_helper.config.mute_ads and data["state"] == "1":
            self.api_helper.create_task(self.mute(False, override=True))

    def _handle_now_playing(self: LoungeAPI, data: NowPlaying) -> None:  # type: ignore
        if self.api_helper.config.mute_ads and data.get("state", "0") == "1":
            self.logger.info("Ad has ended, unmuting")
            self.api_helper.create_task(self.mute(False, override=True))

    def _handle_add_state_change(self: LoungeAPI, data: dict[str, Any]) -> None:  # type: ignore
        ad_state = data["adState"]
        is_skip_enabled = data["isSkipEnabled"] == "true"
        if ad_state == "0":
            self._unmute_ad_ended()
        elif self.api_helper.config.skip_ads and is_skip_enabled:
            self._skip_ad()
        elif self.api_helper.config.mute_ads:
            self._mute_ad_started()

    def _handle_volume_changed(self: LoungeAPI, data: VolumeChanged) -> None:  # type: ignore
        self.volume_state = data

    def _handle_autoplay_up_next(self: LoungeAPI, data: dict[str, Any]) -> None:  # type: ignore
        if data and (vid_id := data["videoId"]):
            self.logger.info(f"Getting segments for next video: {vid_id}")
            self.api_helper.create_task(self.api_helper.get_segments(vid_id))

    def _handle_ad_playing(self: LoungeAPI, data: dict[str, Any]) -> None:  # type: ignore
        vid_id = data.get("contentVideoId")
        is_skip_enabled = data["isSkipEnabled"] == "true"
        if vid_id:
            self.logger.info(f"Getting segments for next video: {vid_id}")
            self.api_helper.create_task(self.api_helper.get_segments(vid_id))
        elif self.api_helper.config.skip_ads and is_skip_enabled:
            self._skip_ad()
        elif self.api_helper.config.mute_ads:
            self._mute_ad_started()

    def _handle_lounge_status(self: LoungeAPI, data: LoungeStatus) -> None:  # type: ignore
        devices: list[Device] = json.loads(data["devices"])
        for device in devices:
            if device["type"] == "LOUNGE_SCREEN":
                device_info: DeviceInfo = json.loads(device.get("deviceInfo", "{}"))
                if device_info.get("clientName", "") in youtube_client_blacklist:
                    self._force_disconnect()

    def _handle_subtitles_track_changed(self: LoungeAPI, data: VideoData) -> None:  # type: ignore
        print(
            "Subtitles track changed",
            data,
            self.shorts_disconnected,
            self.api_helper.config.handle_shorts,
        )
        if self.shorts_disconnected and self.api_helper.config.handle_shorts:
            video_id_saved = data.get("videoId", None)
            self.shorts_disconnected = False
            self.api_helper.create_task(self.play_video(video_id_saved))

    def _handle_lounge_screen_disconnected(self: LoungeAPI, data: dict[str, str]) -> None:  # type: ignore
        print(
            "Lounge screen disconnected",
            data,
            self.shorts_disconnected,
            self.api_helper.config.handle_shorts,
        )
        if (
            data
            and data["reason"] == "disconnectedByUserScreenInitiated"
            and self.api_helper.config.handle_shorts
        ):
            self.shorts_disconnected = True

    def _handle_autoplay_mode_changed(self: LoungeAPI) -> None:  # type: ignore
        self.api_helper.create_task(
            self.set_auto_play_mode(self.api_helper.config.autoplay)
        )

    def _unmute_ad_ended(self: LoungeAPI) -> None:  # type: ignore
        self.logger.info("Ad has ended, unmuting")
        self.api_helper.create_task(self.mute(False, override=True))

    def _skip_ad(self: LoungeAPI) -> None:  # type: ignore
        self.logger.info("Ad can be skipped, skipping")
        self.api_helper.create_task(self.skip_ad())
        self.api_helper.create_task(self.mute(False, override=True))

    def _mute_ad_started(self: LoungeAPI) -> None:  # type: ignore
        self.logger.info("Ad has started, muting")
        self.api_helper.create_task(self.mute(True, override=True))

    def _force_disconnect(self: LoungeAPI) -> None:  # type: ignore
        self._sid = None
        self._gsession = None
