
from __future__ import annotations
from typing import TYPE_CHECKING, Any

import json

from .constants import youtube_client_blacklist

if TYPE_CHECKING:
    from .lounge import LoungeAPI
    from ._types.events import *

__all__ = ("WithEventsHandlers",)


class WithEventsHandlers:
    def _handle_state_change(self: LoungeAPI, data: OnStateChange) -> None:# type: ignore
        print(f"State change: {data}")
        if self.api_helper.config.mute_ads and data["state"] == "1":
            self.api_helper.create_task(self.mute(mute=False, override=True))

    def _handle_now_playing(self: LoungeAPI, data: NowPlaying) -> None:# type: ignore
        if self.api_helper.config.mute_ads and data.get("state", "0") == "1":
            self.logger.info("Ad has ended, unmuting")
            self.api_helper.create_task(self.mute(mute=False, override=True))

    def _handle_add_state_change(
        self: LoungeAPI,# type: ignore
        data: dict[str, Any],
    ) -> None:
        skip_ads = self.api_helper.config.skip_ads
        mute_ads = self.api_helper.config.mute_ads

        print(f"Ad state change: {data}")
        if data["adState"] == "0" and data["currentTime"] != "0":  # Ad is not playing
            self.logger.info("Ad has ended, unmuting")
            self.api_helper.create_task(self.mute(False, override=True))
        
        if (
            skip_ads and data["isSkipEnabled"] == "true"
        ):  # YouTube uses strings for booleans
            self.logger.info("Ad can be skipped, skipping")
            self.api_helper.create_task(self.skip_ad())
            self.api_helper.create_task(self.mute(False, override=True))
        elif mute_ads:  # Seen multiple other adStates, assuming they are all ads
            self.logger.info("Ad has started, muting")
            self.api_helper.create_task(self.mute(True, override=True))

    def _handle_volume_changed(self: LoungeAPI, data: VolumeChanged) -> None:# type: ignore
        self.volume_state = data

    def _handle_autoplay_up_next(
        self: LoungeAPI,# type: ignore
        data: dict[str, Any],
    ) -> None:
        if data and (vid_id := data["videoId"]):
            self.logger.info("Getting segments for next video: %s", vid_id)
            self.api_helper.create_task(self.get_segments(vid_id))

    def _handle_ad_playing(
        self: LoungeAPI,# type: ignore
        data: dict[str, Any],
    ) -> None:
        skip_ads = self.api_helper.config.skip_ads
        mute_ads = self.api_helper.config.mute_ads
        if vid_id := data["contentVideoId"]:
            self.logger.info(f"Getting segments for next video: {vid_id}")
            self.api_helper.create_task(self.get_segments(vid_id))

        if (
            skip_ads and data["isSkipEnabled"] == "true"
        ):  # YouTube uses strings for booleans
            self.logger.info("Ad can be skipped, skipping")
            self.api_helper.create_task(self.skip_ad())
            self.api_helper.create_task(self.mute(False, override=True))
        elif mute_ads:  # Seen multiple other adStates, assuming they are all ads
            self.logger.info("Ad has started, muting")
            self.api_helper.create_task(self.mute(True, override=True))

    def _handle_lounge_status(self: LoungeAPI, data: LoungeStatus) -> None:# type: ignore
        devices: list[Device] = json.loads(data["devices"])
        for device in devices:
            if device["type"] == "LOUNGE_SCREEN":
                device_info: DeviceInfo = json.loads(device.get("deviceInfo", "{}"))
                if device_info.get("clientName", "") in youtube_client_blacklist:
                    self._force_disconnect()


    def _handle_subtitles_track_changed(self: LoungeAPI, data: VideoData) -> None:# type: ignore
        if self.shorts_disconnected and self.api_helper.config.handle_shorts:
            video_id_saved = data.get("videoId", None)
            self.shorts_disconnected = False
            self.api_helper.create_task(self.play_video(video_id_saved))

    def _handle_lounge_screen_disconnected(
        self: LoungeAPI,# type: ignore
        data: dict[str, str],
    ) -> None:
        if (
            data
            and data["reason"] == "disconnectedByUserScreenInitiated"
            and self.api_helper.config.handle_shorts
        ):
            self.shorts_disconnected = True

    def _handle_autoplay_mode_changed(
        self: LoungeAPI,# type: ignore
    ) -> None:
        self.api_helper.create_task(
            self.set_auto_play_mode(self.api_helper.config.autoplay)
        )

    def _unmute_ad_ended(
        self: LoungeAPI,# type: ignore
    ) -> None:
        self.logger.info("Ad has ended, unmuting")
        self.api_helper.create_task(self.mute(False, override=True))

    def _skip_ad(self: LoungeAPI) -> None:# type: ignore
        self.logger.info("Ad can be skipped, skipping")
        self.api_helper.create_task(self.skip_ad())
        self.api_helper.create_task(self.mute(False, override=True))

    def _mute_ad_started(
        self: LoungeAPI,# type: ignore
    ) -> None:
        self.logger.info("Ad has started, muting")
        self.api_helper.create_task(self.mute(True, override=True))

    def _force_disconnect(
        self: LoungeAPI,# type: ignore
    ) -> None:
        self._sid = None
        self._gsession = None
