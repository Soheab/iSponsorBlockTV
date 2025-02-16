from __future__ import annotations
from typing import TYPE_CHECKING, Any, TypedDict
from collections.abc import Coroutine

import enum
import html
import asyncio
import hashlib
import logging

import aiohttp
from async_utils.task_cache import lrutaskcache

from src import constants, dial_client

if TYPE_CHECKING:
    from src._types.video import Video, VideoListResponse

    from .config import Config, ChannelConfig

__all__ = ("APIHelper",)


class Segment(TypedDict):
    category: str
    actionType: str
    segment: list[float]  # [start, end]
    UUID: str
    videoDuration: float
    locked: int
    votes: int
    description: str


class SegmentsResponse(TypedDict):
    videoID: str
    segments: list[Segment]


class ProcessedSegment(TypedDict):
    start: float
    end: float
    UUID: list[str]


class SegmentsHandleStatus(enum.IntEnum):
    SUCCESS = enum.auto()
    NO_DATA = enum.auto()
    LOCKED = enum.auto()
    ERROR = enum.auto()


class SegmentsHandler:
    def __init__(self, *, api_helper: APIHelper) -> None:
        self.api_helper: APIHelper = api_helper

    async def get_video_segments(self, video_id: str) -> list[SegmentsResponse]:
        """Fetch video segments from the API using the provided video ID."""
        vid_id_hashed = hashlib.sha256(video_id.encode("utf-8")).hexdigest()[:4]
        params = {
            "category": self.api_helper.config.skip_categories,
            "actionType": constants.SponsorBlock_actiontype,
            "service": constants.SponsorBlock_service,
        }
        headers = {"Accept": "application/json"}
        url = f"{constants.SponsorBlock_api}skipSegments/{vid_id_hashed}"

        try:
            async with self.api_helper.web_session.get(
                url, headers=headers, params=params
            ) as response:
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as e:
            logging.getLogger(__name__).exception(
                "Error getting segments for video %s, hashed as %s: %s",
                video_id,
                vid_id_hashed,
                str(e),  # noqa: TRY401
                exc_info=e,
            )
            return []

    def _sort_and_merge_segments(self, segments: list[Segment]) -> list[Segment]:
        """Sort segments by start time and merge overlapping segments."""
        if not segments:
            return []

        segments.sort(key=lambda x: x["segment"][0])
        merged_segments: list[Segment] = []
        for segment in segments:
            if (
                merged_segments
                and segment["segment"][0] <= merged_segments[-1]["segment"][1]
            ):
                # Merge overlapping segments
                merged_segments[-1]["segment"][1] = max(
                    merged_segments[-1]["segment"][1], segment["segment"][1]
                )
            else:
                # Add non-overlapping segment
                merged_segments.append(segment)
        return merged_segments

    def _process_segments(
        self, segments: list[Segment], *, minimum_skip_length: int
    ) -> list[ProcessedSegment]:
        """Process segments by merging close segments and filtering by minimum length."""
        processed_segments: list[ProcessedSegment] = []
        for segment in segments:
            segment_dict: ProcessedSegment = {
                "start": segment["segment"][0],
                "end": segment["segment"][1],
                "UUID": [segment["UUID"]],
            }

            if (
                processed_segments
                and segment_dict["start"] - processed_segments[-1]["end"] < 1
            ):
                # Extend the previous segment
                processed_segments[-1]["end"] = segment_dict["end"]
                processed_segments[-1]["UUID"].extend(segment_dict["UUID"])
            else:
                # Add a new segment
                processed_segments.append(segment_dict)

        # Filter by minimum skip length
        return [
            segment
            for segment in processed_segments
            if segment["end"] - segment["start"] > minimum_skip_length
        ]

    async def get_segments(
        self, *, video_id: str, minimal_skip_length: int
    ) -> list[ProcessedSegment]:
        """Retrieve, sort, and process segments for a video."""
        segments = await self.get_video_segments(video_id)
        if not segments:
            return []

        # Filter segments by video ID
        filtered_segments = [
            segment for segment in segments if segment.get("videoID") == video_id
        ]
        if not filtered_segments:
            return []

        # Extract the actual segments from the filtered result
        segments_list = filtered_segments[0].get("segments", [])

        sorted_segments = self._sort_and_merge_segments(segments_list)
        if not sorted_segments:
            return []

        return self._process_segments(
            sorted_segments, minimum_skip_length=minimal_skip_length
        )


class APIHelper:
    def __init__(
        self,
        *,
        config: Config,
        web_session: aiohttp.ClientSession,
    ) -> None:
        self.config: Config = config
        self.web_session: aiohttp.ClientSession = web_session
        self.dial_client = dial_client.DialClient(web_session)
        self.tasks: set[asyncio.Task[Any]] = set()
        self.segments_handler = SegmentsHandler(api_helper=self)

    def create_task(
        self, coro: Coroutine[Any, Any, Any] | asyncio.Task[Any]
    ) -> asyncio.Task[Any]:
        """Create and track an asyncio task."""
        if isinstance(coro, asyncio.Task):
            return coro

        task = asyncio.create_task(coro)
        task.add_done_callback(self.tasks.discard)
        self.tasks.add(task)
        return task

    @lrutaskcache(maxsize=100, cache_transform=lambda args, kwargs: ((), kwargs))
    async def get_video_id(
        self,
        *,
        title: str,
        artist: str,
    ) -> tuple[str, str] | None:
        """Fetch video ID from YouTube API using title and artist."""
        params = {
            "q": f"{title} {artist}",
            "key": self.config.apikey,
            "part": "snippet",
        }
        url = f"{constants.Youtube_api}search"
        async with self.web_session.get(url, params=params) as resp:
            data = await resp.json()

        if "error" in data:
            return None

        for item in data["items"]:
            if item["id"]["kind"] != "youtube#video":
                continue
            title_api = html.unescape(item["snippet"]["title"])
            artist_api = html.unescape(item["snippet"]["channelTitle"])
            if title_api == title and artist_api == artist:
                return item["id"]["videoId"], item["snippet"]["channelId"]
        return None

    @lrutaskcache(maxsize=100, cache_transform=lambda args, kwargs: (args[1], {}))
    async def is_whitelisted(self, video_id: str) -> bool:
        """Check if the video's channel is whitelisted."""
        whitelisted_channels: list[ChannelConfig] = self.config.channel_whitelist
        if not whitelisted_channels or not self.config.apikey:
            return False

        channel_id = await self.get_channel_id(video_id)
        return any(i["id"] == channel_id for i in whitelisted_channels)

    @lrutaskcache(maxsize=100, cache_transform=lambda args, kwargs: (args[1], {}))
    async def get_channel_id(self, video_id: str) -> str | None:
        """Fetch channel ID for a given video ID."""
        params = {
            "id": video_id,
            "key": self.config.apikey,
            "part": "snippet",
        }
        url = f"{constants.Youtube_api}videos"
        async with self.web_session.get(url, params=params) as resp:
            data = await resp.json()

        if "error" in data or not data.get("items"):
            return None
        return data["items"][0]["snippet"]["channelId"]

    @lrutaskcache(maxsize=50, cache_transform=lambda args, kwargs: (args[1], {}))
    async def search_channels(self, channel: str) -> list[Any]:
        """Search for channels on YouTube."""
        api_key: str = self.config.apikey
        channels: list[Any] = []
        params = {
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

        for item in data["items"]:
            params = {
                "id": item["snippet"]["channelId"],
                "key": api_key,
                "part": "statistics",
            }
            url = f"{constants.Youtube_api}channels"
            async with self.web_session.get(url, params=params) as resp:
                channel_data = await resp.json()

            statics = channel_data["items"][0]["statistics"]
            sub_count = (
                "Hidden"
                if "hiddenSubscriberCount" in statics
                else format(int(statics["subscriberCount"]), "_")
            )
            channels.append(
                (
                    item["snippet"]["channelId"],
                    item["snippet"]["channelTitle"],
                    sub_count,
                )
            )
        return channels

    @lrutaskcache(maxsize=100, cache_transform=lambda args, kwargs: (args[1], {}))
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

    async def mark_viewed_segments(self, uuids: list[str]) -> None:
        """Mark the segments as viewed in the SponsorBlock API."""
        if not self.config.skip_count_tracking:
            return

        url = f"{constants.SponsorBlock_api}viewedVideoSponsorTime/"
        tasks = [self.web_session.post(url, params={"UUID": uuid}) for uuid in uuids]
        await asyncio.gather(*tasks)

    async def discover_youtube_devices_dial(self) -> list[Any]:
        """Discover YouTube devices using DIAL."""
        return await self.dial_client.discover()

    async def close(self) -> None:
        """Cancel all pending tasks and clear the task set."""
        for task in self.tasks:
            task.cancel()
        self.tasks.clear()
