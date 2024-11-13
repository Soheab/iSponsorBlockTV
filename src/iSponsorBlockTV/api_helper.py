from __future__ import annotations

import asyncio
import hashlib
import html
import json
import logging
from collections.abc import Coroutine
from functools import cached_property
from typing import TYPE_CHECKING, Any

import aiohttp
import discord

from iSponsorBlockTV.conditional_ttl_cache import AsyncConditionalTTL

from . import constants, dial_client
from .sinbad_cache import lrutaskcache
from .utils import list_to_tuple

if TYPE_CHECKING:
    from ..discord_bot import BlockBotClient
    from ..types.video import Video, VideoListResponse
    from .config import ChannelConfig, Config
    from .lounge import LoungeAPI

__all__ = ("APIHelper",)


class ProcessSegments:
    def __init__(self, api_helper: APIHelper) -> None:
        self.web_session = api_helper.web_session
        self.config = api_helper.config
        self._api_helper = api_helper

    async def __get_channel_id(self, video_id: str) -> str | None:
        params = {"id": video_id, "key": self.config.apikey, "part": "snippet"}
        url = f"{constants.Youtube_api}videos"

        async with self.web_session.get(url, params=params) as resp:
            data = await resp.json()

        if "error" in data:
            return None
        item = data["items"][0]
        if item["kind"] != "youtube#video":
            return None
        return item["snippet"]["channelId"]

    @lrutaskcache(maxsize=100)
    async def is_whitelisted(self, video_id: str) -> bool:
        whitelisted_channels = self.config.channel_whitelist
        if not whitelisted_channels or not self.config.apikey:
            return False

        channel_id = await self.__get_channel_id(video_id)
        return any(channel["id"] == channel_id for channel in whitelisted_channels)

    @lrutaskcache(ttl=300, maxsize=10)
    async def get_segments(self, video_id: str) -> tuple[list[dict[str, int]], bool]:
        if await self.is_whitelisted(video_id):
            print("whitelisted")
            return [], True

        vid_id_hashed = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:4]
        params = {
            "category": self.config.skip_categories,
            "actionType": constants.SponsorBlock_actiontype,
            "service": constants.SponsorBlock_service,
        }
        headers = {"Accept": "application/json"}
        url = constants.SponsorBlock_api + "skipSegments/" + vid_id_hashed
        async with self.web_session.get(
            url, headers=headers, params=params
        ) as response:
            response_json = await response.json()
        if response.status != 200:
            response_text = await response.text()
            print(
                f"Error getting segments for video {video_id}, hashed as {vid_id_hashed}."
                f" Code: {response.status} - {response_text}"
            )
            return [], True
        for i in response_json:
            if str(i["videoID"]) == str(video_id):
                response_json = i
                break

        return self.process_segments(response_json)

    @staticmethod
    def process_segments(response: dict[Any, Any]) -> tuple[list[dict[str, int]], bool]:
        print("process_segments response", response)
        segments = []
        ignore_ttl = True
        try:
            response_segments = response["segments"]
            # sort by end
            response_segments.sort(key=lambda x: x["segment"][1])
            # extend ends of overlapping segments to make one big segment
            for i in response_segments:
                for j in response_segments:
                    if j["segment"][0] <= i["segment"][1] <= j["segment"][1]:
                        i["segment"][1] = j["segment"][1]

            # sort by start
            response_segments.sort(key=lambda x: x["segment"][0])
            # extend starts of overlapping segments to make one big segment
            for i in reversed(response_segments):
                for j in reversed(response_segments):
                    if j["segment"][0] <= i["segment"][0] <= j["segment"][1]:
                        i["segment"][0] = j["segment"][0]

            for i in response_segments:
                ignore_ttl = (
                    ignore_ttl and i["locked"] == 1
                )  # If all segments are locked, ignore ttl
                segment = i["segment"]
                UUID = i["UUID"]
                segment_dict = {"start": segment[0], "end": segment[1], "UUID": [UUID]}
                try:
                    # Get segment before to check if they are too close to each other
                    segment_before_end = segments[-1]["end"]
                    segment_before_start = segments[-1]["start"]
                    segment_before_UUID = segments[-1]["UUID"]

                except Exception:
                    segment_before_end = -10
                if (
                    segment_dict["start"] - segment_before_end < 1
                ):  # Less than 1 second apart, combine them and skip them together
                    segment_dict["start"] = segment_before_start
                    segment_dict["UUID"].extend(segment_before_UUID)
                    segments.pop()
                segments.append(segment_dict)
        except Exception:
            pass

        print("processed segments", segments)
        return segments, ignore_ttl


class EnsureSession(aiohttp.ClientSession):
    def __init__(self, web_session: aiohttp.ClientSession) -> None:
        self._web_session: aiohttp.ClientSession = web_session

    async def _request(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return await self.get_session()._request(*args, **kwargs)
        except aiohttp.ClientConnectionError:
            self._web_session = aiohttp.ClientSession(
                connector=self._web_session.connector
            )
            return await self.get_session()._request(*args, **kwargs)

    def get_session(self) -> aiohttp.ClientSession:
        if self._web_session.closed:
            self._web_session = aiohttp.ClientSession(
                connector=self._web_session.connector
            )
        return self._web_session

    def __getattr__(self, name: str) -> Any:
        if name == "_request":
            return self._request
        return getattr(self.get_session(), name)


class APIHelper:
    def __init__(
        self,
        *,
        config: Config,
        web_session: aiohttp.ClientSession,
        discord_client: BlockBotClient | None = None,
    ) -> None:
        self.config: Config = config
        self.web_session: aiohttp.ClientSession = web_session
        self.discord_client: BlockBotClient | None = discord_client

        self.tasks: set[asyncio.Task] = set()

        self._current_video_message_id: int | None = None

        #self._segments_processor = ProcessSegments(self)

    @cached_property
    def current_video_webhook(self) -> discord.Webhook:
        if not self.config.current_video_webhook or not self.discord_client:
            msg = "No current video webhook set or discord client provided"
            raise ValueError(msg)

        return discord.Webhook.partial(
            id=int(self.config.current_video_webhook["id"]),
            token=self.config.current_video_webhook["token"],
            session=self.web_session,
            client=self.discord_client,
        )

    async def send_current_video_webhook(
        self, lounge: LoungeAPI, video_id: str
    ) -> None:
        webhook = self.current_video_webhook

        video = lounge.current_video_data or await self.get_video_from_id(video_id)
        if not video:
            return

        from video_player import VideoPlayer

        view = VideoPlayer(video, lounge)
        embed = view.embed
        kwgrs = {
            "view": view,
            "embed": embed,
        }

        try:
            if self._current_video_message_id:
                await webhook.edit_message(
                    message_id=self._current_video_message_id,
                    **kwgrs,
                )
            else:
                if self.discord_client:
                    self.discord_client.purge_all_video_messages()

                message = await webhook.send(
                    **kwgrs,
                    wait=True,
                )
                self._current_video_message_id = message.id
        except discord.HTTPException as e:
            if self.discord_client:
                self.discord_client.logs_webhook.send(
                    f"Error sending current video webhook: {e}"
                )
            self._current_video_message_id = None
            await self.send_current_video_webhook(lounge, video_id)

    def create_task(
        self, coro: Coroutine[Any, Any, Any] | asyncio.Task[Any]
    ) -> asyncio.Task:
        if isinstance(coro, asyncio.Task):
            return coro

        task = asyncio.create_task(coro)
        task.add_done_callback(lambda fut: self.tasks.discard(fut))
        self.tasks.add(task)
        return task

    @lrutaskcache(maxsize=10)
    async def get_video_id(
        self,
        *,
        title: str,
        artist: str,
    ) -> tuple[str, str] | None:
        params: dict[str, str] = {
            "q": title + " " + artist,
            "key": self.config.apikey,
            "part": "snippet",
        }
        url: str = f"{constants.Youtube_api}search"
        async with self.web_session.get(url, params=params) as resp:
            data = await resp.json()

        if "error" in data:
            return None

        for i in data["items"]:
            if i["id"]["kind"] != "youtube#video":
                continue
            title_api = html.unescape(i["snippet"]["title"])
            artist_api = html.unescape(i["snippet"]["channelTitle"])
            if title_api == title and artist_api == artist:
                return i["id"]["videoId"], i["snippet"]["channelId"]
        return None

    @lrutaskcache(maxsize=100)
    async def is_whitelisted(self, vid_id: str) -> bool:
        whitelisted_channels: list[ChannelConfig] = self.config.channel_whitelist
        if not whitelisted_channels or not self.config.apikey:
            return False

        channel_id = await self.__get_channel_id(vid_id)
        # check if channel id is in whitelist
        return any(i["id"] == channel_id for i in whitelisted_channels)

    async def __get_channel_id(
        self,
        video_id: str,
        /,
    ) -> str | None:
        params = {"id": video_id, "key": self.config.apikey, "part": "snippet"}
        url = f"{constants.Youtube_api}videos"

        async with self.web_session.get(url, params=params) as resp:
            data = await resp.json()

        if "error" in data:
            return None
        data = data["items"][0]
        if data["kind"] != "youtube#video":
            return None
        return data["snippet"]["channelId"]

    @lrutaskcache(maxsize=10)
    async def search_channels(self, channel: str) -> list[Any]:
        api_key: str = self.config.apikey

        channels: list[Any] = []
        params: dict[str, str] = {
            "q": channel,
            "key": api_key,
            "part": "snippet",
            "type": "channel",
            "maxResults": "5",
        }
        url = f"{constants.Youtube_api}search"
        async with self.web_session.get(url, params=params) as resp:
            data = await resp.json()

        if "error" in data:
            return channels

        for i in data["items"]:
            # Get channel subscription number
            params = {
                "id": i["snippet"]["channelId"],
                "key": api_key,
                "part": "statistics",
            }
            url: str = constants.Youtube_api + "channels"
            async with self.web_session.get(url, params=params) as resp:
                channel_data = await resp.json()

            sub_count: str
            statics = channel_data["items"][0]["statistics"]
            if "hiddenSubscriberCount" in statics:
                sub_count = "Hidden"
            else:
                sub_count = statics["subscriberCount"]
                sub_count: str = format(sub_count, "_")

            channels.append(
                (i["snippet"]["channelId"], i["snippet"]["channelTitle"], sub_count)
            )
        return channels

    async def get_video_from_id(self, video_id: str, /) -> Video | None:
        part = "snippet,contentDetails,statistics"
        params: dict[str, str] = {
            "id": video_id,
            "key": self.config.apikey,
            "part": part,
        }
        url = f"{constants.Youtube_api}videos"
        async with self.web_session.get(url, params=params) as resp:
            data: VideoListResponse = await resp.json()

        if "error" in data or not data or not data["items"]:
            return None

        return data["items"][0]

    @list_to_tuple  # Convert list to tuple so it can be used as a key in the cache
    @AsyncConditionalTTL(
        time_to_live=300, maxsize=10
    )  # 5 minutes for non-locked segments
    async def get_segments(self, vid_id):
        if await self.is_whitelisted(vid_id):
            return (
                [],
                True,
            )  # Return empty list and True to indicate that the cache should last forever
        vid_id_hashed = hashlib.sha256(vid_id.encode("utf-8")).hexdigest()[
            :4
        ]  # Hashes video id and gets the first 4 characters
        params = {
            "category": self.config.skip_categories,
            "actionType": constants.SponsorBlock_actiontype,
            "service": constants.SponsorBlock_service,
        }
        headers = {"Accept": "application/json"}
        url = constants.SponsorBlock_api + "skipSegments/" + vid_id_hashed
        async with self.web_session.get(
            url, headers=headers, params=params
        ) as response:
            response_json = await response.json()
        if response.status != 200:
            response_text = await response.text()
            print(
                f"Error getting segments for video {vid_id}, hashed as {vid_id_hashed}."
                f" Code: {response.status} - {response_text}"
            )
            return [], True
        for i in response_json:
            if str(i["videoID"]) == str(vid_id):
                response_json = i
                break
        return self.process_segments(response_json)

    @staticmethod
    def process_segments(response):
        segments = []
        ignore_ttl = True
        try:
            response_segments = response["segments"]
            # sort by end
            response_segments.sort(key=lambda x: x["segment"][1])
            # extend ends of overlapping segments to make one big segment
            for i in response_segments:
                for j in response_segments:
                    if j["segment"][0] <= i["segment"][1] <= j["segment"][1]:
                        i["segment"][1] = j["segment"][1]

            # sort by start
            response_segments.sort(key=lambda x: x["segment"][0])
            # extend starts of overlapping segments to make one big segment
            for i in reversed(response_segments):
                for j in reversed(response_segments):
                    if j["segment"][0] <= i["segment"][0] <= j["segment"][1]:
                        i["segment"][0] = j["segment"][0]

            for i in response_segments:
                ignore_ttl = (
                    ignore_ttl and i["locked"] == 1
                )  # If all segments are locked, ignore ttl
                segment = i["segment"]
                UUID = i["UUID"]
                segment_dict = {"start": segment[0], "end": segment[1], "UUID": [UUID]}
                try:
                    # Get segment before to check if they are too close to each other
                    segment_before_end = segments[-1]["end"]
                    segment_before_start = segments[-1]["start"]
                    segment_before_UUID = segments[-1]["UUID"]

                except Exception:
                    segment_before_end = -10
                if (
                    segment_dict["start"] - segment_before_end < 1
                ):  # Less than 1 second apart, combine them and skip them together
                    segment_dict["start"] = segment_before_start
                    segment_dict["UUID"].extend(segment_before_UUID)
                    segments.pop()
                segments.append(segment_dict)
        except Exception:
            pass
        return segments, ignore_ttl

    async def mark_viewed_segments(self, uuids: list[str]) -> None:
        """Marks the segments as viewed in the SponsorBlock API, if skip_count_tracking is enabled.
        Lets the contributor know that someone skipped the segment (thanks)"""
        if self.config.skip_count_tracking:
            for i in uuids:
                url = constants.SponsorBlock_api + "viewedVideoSponsorTime/"
                params = {"UUID": i}
                await self.web_session.post(url, params=params)

    async def discover_youtube_devices_dial(self) -> list[Any]:
        """Discovers YouTube devices using DIAL"""
        return await dial_client.discover(self.web_session)
        # print(dial_screens)

    async def close(self) -> None:
        for task in self.tasks:
            try:
                await asyncio.sleep(0)
                task.cancel()
            except asyncio.CancelledError:
                pass

        self.tasks.clear()
