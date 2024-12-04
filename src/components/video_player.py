from __future__ import annotations
from typing import TYPE_CHECKING, NamedTuple

from datetime import datetime

import discord

from .wait_for_modal import SimpleModalWaitFor

if TYPE_CHECKING:
    from src.types.video import Video
    from src.types.events import VolumeChanged

    from ..video import CurrentVideo
    from ..lounge import LoungeAPI


class CurrentSettings(NamedTuple):
    volume: int
    is_muted: bool
    is_paused: bool


class VideoPlayer(discord.ui.View):
    def __init__(
        self,
        video: Video,
        lounge_controller: LoungeAPI,
        /,
        *,
        timeout: float | None = None,
    ) -> None:
        super().__init__(timeout=timeout)

        self.video: Video = video
        self.lounge_controller: LoungeAPI = lounge_controller

        self.current_video: CurrentVideo | None = lounge_controller.current_video

        self.volume: int | None = None
        self.is_muted: bool = False
        self.is_paused: bool = False
        self.volume_state: VolumeChanged | None = None

    @staticmethod
    def parse_time(time: str) -> int:
        if ":" in time:
            splitted = time.split(":")
            if len(splitted) == 2:
                minutes, seconds = splitted
                return int(minutes) * 60 + int(seconds)

            hours, minutes, seconds = splitted
            return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
        return int(time)

    @property
    def embed(self) -> discord.Embed:
        volume_state = self.lounge_controller.volume_state
        self.volume = int(volume_state["volume"])
        self.is_muted = volume_state["muted"] == "true" or self.volume == 0
        self.is_paused = self.lounge_controller.paused

        snippet = self.video["snippet"]
        thumbnail: str = snippet["thumbnails"]["standard"]["url"]
        embed = discord.Embed(
            title=snippet["title"],
            description=(
                self.current_video.progress_bar(length=20)
                if self.current_video
                else None
            ),
            color=0xFF0000,
        )
        embed.set_image(url=thumbnail)
        embed.set_author(name=f"{snippet["channelTitle"]} - {self.video['id']}")

        published_at = datetime.strptime(snippet["publishedAt"], "%Y-%m-%dT%H:%M:%SZ")  # type: ignore # noqa: DTZ007
        formatted_published_at = published_at.strftime("%B %d, %Y")
        formatted_published_at_stamp = discord.utils.format_dt(published_at, "R")

        published_at = f"{formatted_published_at} ({formatted_published_at_stamp})"
        likes = format(int(self.video["statistics"]["likeCount"]), ",d")
        views = format(int(self.video["statistics"]["viewCount"]), ",d")
        comments = format(int(self.video["statistics"]["commentCount"]), ",d")

        combined_fields = {
            "Channel Info": (
                f"Channel ID: {snippet['channelId']}\nPublished At: {published_at}",
                False,
            ),
            "Statistics": (
                f"Views: {views}\nLikes: {likes}" f"\nComments: {comments}",
                True,
            ),
            "Playback": (
                f"Volume: {self.volume or 0}\nMuted: {self.is_muted}\nPaused: {self.is_paused}",
                True,
            ),
        }

        for name, (value, inline) in combined_fields.items():
            embed.add_field(name=name, value=value, inline=inline)

        return embed

    @discord.ui.button(
        label="Previous", style=discord.ButtonStyle.secondary, emoji="⏮️", row=0
    )
    async def previous_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        await self.lounge_controller.previous()

    @discord.ui.button(
        label="Play", style=discord.ButtonStyle.success, emoji="▶️", row=1
    )
    async def play_pause_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        await self.lounge_controller.play()
        self.is_paused = False

    @discord.ui.button(
        label="Pause", style=discord.ButtonStyle.danger, emoji="⏸️", row=1
    )
    async def pause_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        await self.lounge_controller.pause()
        self.is_paused = True

    @discord.ui.button(
        label="Next", style=discord.ButtonStyle.secondary, emoji="⏭️", row=0
    )
    async def next_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        await self.lounge_controller.next()

    @discord.ui.button(
        label="Seek To", style=discord.ButtonStyle.secondary, emoji="⏱️", row=1
    )
    async def seek_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        modal = SimpleModalWaitFor(
            title="Seek To",
            input_label="Time as number",
            input_min_length=1,
            input_max_length=5,
            forced_type=str,
            input_placeholder="totaal seconds of hh:mm:ss or mm:ss or total seconds",
        )
        await interaction.response.send_modal(modal)
        res = await modal.wait()
        await modal.interaction.response.defer()  # type: ignore
        if res is True:
            return

        time = modal.value
        if not time:
            return

        await self.lounge_controller.seek_to(self.parse_time(time))

    @discord.ui.button(
        label="Set Volume", style=discord.ButtonStyle.secondary, emoji="🔊", row=1
    )
    async def volume_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        modal = SimpleModalWaitFor(
            title="Set Volume",
            input_label="Volume in seconds",
            input_min_length=1,
            input_max_length=3,
            forced_type=int,
            input_placeholder="0-100 (0 to mute)",
        )
        await interaction.response.send_modal(modal)
        res = await modal.wait()
        if modal.interaction:
            await modal.interaction.response.defer()  # type: ignore
        if res is True:
            return

        volume = modal.value
        if not volume:
            return

        if volume <= 0:
            await self.lounge_controller.mute(True, override=True)
            self.is_muted = True
            self.volume = 0
        else:
            await self.lounge_controller.set_volume(volume)
            self.volume = volume

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹️", row=3)
    async def stop_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.send_message("Stopping video", ephemeral=True)
        await self.lounge_controller.disconnect()

    @discord.ui.button(
        label="Skip AD (if possible)",
        style=discord.ButtonStyle.secondary,
        emoji="⏭️",
        row=3,
    )
    async def skip_ad_button(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.defer()
        await self.lounge_controller.skip_ad()

    async def update(
        self,
        video: Video,
    ) -> None:
        self.video = video
        self.is_paused = False
        self.is_muted = False
        self.volume = None

    async def send(
        self,
        channel: discord.TextChannel,
        video: Video,
    ) -> None: ...
