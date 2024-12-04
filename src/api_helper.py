from __future__ import annotations
from typing import TYPE_CHECKING, Any
from collections.abc import Coroutine

import html
import asyncio
import hashlib
import logging
from functools import cached_property

import aiohttp
import discord

from src import constants, dial_client

from .cache import lrutaskcache

if TYPE_CHECKING:
    from main import BlockBotClient

    from .config import Config, ChannelConfig
    from .lounge import LoungeAPI
    from .types.video import Video, VideoListResponse

__all__ = ("APIHelper",)


class ProcessSegments:
    def __init__(self, api_helper: APIHelper) -> None:
        self.web_session: aiohttp.ClientSession = api_helper.web_session
        self.config: Config = api_helper.config
        self._api_helper: APIHelper = api_helper

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

    # @list_to_tuple
    @lrutaskcache(ttl=300, maxsize=10)
    async def get_segments(self, video_id: str) -> tuple[list[dict[str, int]], bool]:
        if await self.is_whitelisted(video_id):
            return [], True

        vid_id_hashed = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:4]
        params = {
            "category": self.config.skip_categories,
            "actionType": constants.SponsorBlock_actiontype,
            "service": constants.SponsorBlock_service,
        }
        headers = {"Accept": "application/json"}
        url = f"{constants.SponsorBlock_api}skipSegments/{vid_id_hashed}"

        async with self.web_session.get(
            url, headers=headers, params=params
        ) as response:
            if response.status != 200:
                logging.error(
                    f"Error getting segments for video {video_id}, hashed as {vid_id_hashed}. "
                    f"Code: {response.status} - {response.reason}"
                )
                return [], True

            response_json = await response.json()

        segments = [
            segment for segment in response_json if segment.get("videoID") == video_id
        ]
        if not segments:
            return [], True

        return self.process_segments(segments[0], self.config.minimum_skip_length)

    @staticmethod
    def process_segments(  # noqa: PLR0912
        response: dict[Any, Any], minimum_skip_length: int
    ) -> tuple[list[dict[str, int]], bool]:
        segments = []
        ignore_ttl = True
        try:
            response_segments = response.get("segments", [])
            if not response_segments:
                return segments, ignore_ttl

            # Sort by end time
            response_segments.sort(key=lambda x: x["segment"][1])

            # Merge overlapping segments by extending their end times
            for i in range(len(response_segments)):
                for j in range(i + 1, len(response_segments)):
                    if (
                        response_segments[j]["segment"][0]
                        <= response_segments[i]["segment"][1]
                    ):
                        response_segments[i]["segment"][1] = max(
                            response_segments[i]["segment"][1],
                            response_segments[j]["segment"][1],
                        )

            # Sort by start time
            response_segments.sort(key=lambda x: x["segment"][0])

            # Merge overlapping segments by extending their start times
            for i in range(len(response_segments) - 1, -1, -1):
                for j in range(i - 1, -1, -1):
                    if (
                        response_segments[j]["segment"][1]
                        >= response_segments[i]["segment"][0]
                    ):
                        response_segments[i]["segment"][0] = min(
                            response_segments[i]["segment"][0],
                            response_segments[j]["segment"][0],
                        )

            for segment in response_segments:
                ignore_ttl = ignore_ttl and segment.get("locked", 0) == 1
                segment_dict = {
                    "start": segment["segment"][0],
                    "end": segment["segment"][1],
                    "UUID": [segment["UUID"]],
                }

                if segments and segment_dict["start"] - segments[-1]["end"] < 1:
                    segments[-1]["end"] = segment_dict["end"]
                    segments[-1]["UUID"].extend(segment_dict["UUID"])

                skip_lenght = segment_dict["end"] - segment_dict["start"]
                # Only add segments greater than minimum skip length
                if skip_lenght > minimum_skip_length:
                    segments.append(segment_dict)
                else:
                    logging.info(
                        f"Skipping segment {segment_dict} as it is ({skip_lenght}) less than the minimum skip length of {minimum_skip_length}"  # noqa: E501
                    )

        except KeyError as e:
            logging.exception("KeyError processing segments.", exc_info=e)
        except Exception as e:
            logging.exception("Unexpected error processing segments.", exc_info=e)

        return segments, ignore_ttl


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
        self.dial_client = dial_client.DialClient(web_session)
        self.discord_client: BlockBotClient | None = discord_client

        self.tasks: set[asyncio.Task] = set()

        self._current_video_message_id: int | None = None
        self._segments_processor = ProcessSegments(self)

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
        await asyncio.sleep(5)
        webhook = self.current_video_webhook

        video = lounge.current_video_data or await self.get_video_from_id(video_id)
        if not video:
            return

        from .components.video_player import VideoPlayer

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

    # @lrutaskcache(ttl=300, maxsize=10)
    async def get_segments(self, video_id: str) -> tuple[list[Any], bool]:
        return await self._segments_processor.get_segments(video_id)

    async def mark_viewed_segments(self, uuids: list[str]) -> None:
        """Marks the segments as viewed in the SponsorBlock API, if skip_count_tracking is enabled.
        Lets the contributor know that someone skipped the segment (thanks)"""
        if not self.config.skip_count_tracking:
            return

        url = f"{constants.SponsorBlock_api}viewedVideoSponsorTime/"
        tasks = [self.web_session.post(url, params={"UUID": uuid}) for uuid in uuids]
        await asyncio.gather(*tasks)

    async def discover_youtube_devices_dial(self) -> list[Any]:
        """Discovers YouTube devices using DIAL"""
        return await self.dial_client.discover()

    async def close(self) -> None:
        for task in self.tasks:
            try:
                await asyncio.sleep(0)
                task.cancel()
            except asyncio.CancelledError:
                pass

        self.tasks.clear()
