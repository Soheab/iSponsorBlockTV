from __future__ import annotations
from typing import Any, Literal
from collections.abc import Sequence

import os
import signal
import asyncio
import logging
from pathlib import Path

import aiohttp
import discord
from discord import app_commands
import pyytlounge
from discord.backoff import ExponentialBackoff
from async_utils.waterfall import Waterfall
import pyytlounge.exceptions

from src.utils import EnsureSession
from src.config import Config
from src.api_helper import APIHelper
from src.device_manager import Device, DeviceManager
from src.components.video_player import VideoPlayer

_log = logging.getLogger(Path(__file__).parts[-1].split(".")[0])


class LogMessage:
    def __init__(self, record: logging.LogRecord, formatted_message: str) -> None:
        self.record: logging.LogRecord = record
        self.formatted_message: str = formatted_message

    def __hash__(self) -> int:
        return hash(self.record)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.record.levelname}>"

    @property
    def embed(self) -> discord.Embed:
        record = self.record
        log = self.formatted_message
        log_prefix = ""
        embed_color = discord.Color.dark_theme()
        if record.levelno == logging.INFO:
            log_prefix = "ℹ️ **INFO**"
            embed_color = discord.Color.blurple()
        elif record.levelno == logging.WARNING:
            log_prefix = "⚠️ **WARNING**"
            embed_color = discord.Color.gold()
        elif record.levelno == logging.ERROR:
            log_prefix = "❌ **ERROR**"
            embed_color = discord.Color.red()
        elif record.levelno == logging.DEBUG:
            log_prefix = "🐞 **DEBUG**"
            embed_color = discord.Color.yellow()

        created = f"<t:{int(record.created)}:R>"
        return discord.Embed(
            title=f"{log_prefix} - {created}",
            description=f"```ansi\n{log}\n```",
            color=embed_color,
        )


class BlockBotClient(discord.Client):
    web_session: aiohttp.ClientSession
    api_helper: APIHelper
    config: Config
    logs_webhook: discord.Webhook

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.none())

        self.tree = app_commands.CommandTree(self)

        self.devices: list[DeviceManager] = []
        self.tasks: set[asyncio.Task[Any]] = set()

        self.whitelisted_channels: dict[str, str] = {}

        self.app_is_running: bool = False

        self.video_channel: discord.TextChannel | None = None
        self.config: Config = Config("config.json")

        self.logs_sender: Waterfall[LogMessage] = Waterfall(
            max_wait=5,
            max_quantity=10,
            async_callback=self.send_logs,
        )

    async def send_logs(self, batch: Sequence[LogMessage]) -> None:
        if not batch:
            return

        await self.logs_webhook.send(embeds=[d.embed for d in batch])

    def create_task(self, coro: Any) -> asyncio.Task[Any]:
        task = asyncio.create_task(coro)
        task.add_done_callback(self.tasks.discard)
        self.tasks.add(task)
        return task

    def set_app_config(self) -> None:
        self.whitelisted_channels = {
            c["id"]: c["name"] for c in self.config.channel_whitelist
        }
        self.config.save()

    async def run_app(self) -> None:
        self.web_session = EnsureSession(
            connector_cls=aiohttp.TCPConnector,
            connector_kwargs={"ttl_dns_cache": 300},  # pyright: ignore[reportAttributeAccessIssue]
        )
        self.api_helper = APIHelper(config=self.config, web_session=self.web_session)

        cdevice: Device

        # Create and connect devices
        for cdevice in self.config.devices:
            device = cdevice.connect(api_helper=self.api_helper, debug=True)
            self.devices.append(device)
            self.create_task(device.start())

        self.app_is_running = True
        _log.info("App started")

    def add_channel_whitelist(self, name: str, channel_id: str) -> None:
        if channel_id in self.whitelisted_channels:
            msg = "Channel already whitelisted"
            raise ValueError(msg)

        self.whitelisted_channels[channel_id] = name

    def remove_channel_whitelist(self, channel_id: str) -> None:
        del self.whitelisted_channels[channel_id]

    async def sync_commands(self) -> None:
        await self.tree.sync()
        await self.tree.sync(guild=discord.Object(1237899371773694102))

    async def setup_hook(self) -> None:
        self.logs_webhook = discord.Webhook.from_url(
            "https://canary.discord.com/api/webhooks/1295860248921247804/z8gMrY9qITCJ8TFqNcS7a9uH0ruqBcNMzfhdJHPJqCIAX75ht11-7RLbeb_QyDIV5Iyf",
            client=self,
        )
        self.set_app_config()
        _log.info(f"Logged in as {self.user}")

        self.create_task(self.run_app())

        # await self.sync_commands()

    async def close_app(
        self,
        disconnect: bool = False,
        off: bool = False,  # noqa: FBT001, FBT002
    ) -> None:
        try:
            _log.info("Closing devices, disconnect? %s", disconnect)
            for device in self.devices:
                _log.info("Closing device %s", device.device.name)

                _log.info("Closing device")
                try:
                    await device.close()
                except Exception as e:  # noqa: BLE001
                    _log.error("Error closing device: %s", exc_info=e)
                else:
                    _log.info("Device closed")

                if off or disconnect:
                    device.cancelled = True

                if disconnect:
                    _log.info("Disconnecting device")
                    try:
                        await device.controller.close()
                    except pyytlounge.exceptions.NotConnectedException:
                        _log.debug("Device %s not connected", device.device.name)
                    except Exception as e:  # noqa: BLE001
                        _log.error("Error disconnecting device: %s", exc_info=e)
                    else:
                        _log.info("Device disconnected")

            _log.info("Closing web session %s", self.web_session)
            try:
                await self.web_session.close()
            except Exception as e:  # noqa: BLE001
                _log.error("Error closing web session: %s", exc_info=e)
            else:
                _log.info("Web session closed")

        except Exception as e:  # noqa: BLE001
            _log.error(f"Error closing app: {e}", exc_info=e)

        self.app_is_running = False
        self.devices = []

        for task in self.tasks:
            try:
                task.cancel()
            except Exception:  # noqa: BLE001, S110
                pass

        self.tasks.clear()
        _log.info("App stopped")

    async def restart_app(self) -> None:
        await self.close_app()
        self.set_app_config()
        await self.run_app()
        _log.info("App restarted")

    async def close(self) -> None:
        await self.close_app()
        _log.info("Bot Closed")
        return await super().close()


client = BlockBotClient()

SERVICE_NAME = "sponsorblocktv"
TOKEN = os.getenv("DISCORD_TOKEN")


class Category(discord.Enum):
    sponsor = "sponsor"
    selfpromo = "selfpromo"
    intro = "intro"
    outro = "outro"
    music_offtopic = "music_offtopic"
    interaction = "interaction"
    exclusive_access = "exclusive_access"
    poi_highlight = "poi_highlight"
    preview = "preview"
    filler = "filler"


class CategorySelector(discord.ui.Select[discord.ui.View]):
    view: discord.ui.View

    def __init__(self) -> None:
        options = [
            discord.SelectOption(
                label=category.value,
                value=category.value,
                default=category.value in client.config.skip_categories,
            )
            for category in Category
        ]
        super().__init__(
            placeholder="Select the categories to skip",
            options=options,
            min_values=0,
            max_values=len(options),
        )

    async def callback(self, interaction: discord.Interaction) -> None:
        chosen = self.values
        for opt in self.options:
            if opt.value in chosen:
                if opt.value not in client.config.skip_categories:
                    client.config.skip_categories.append(opt.value)
            elif opt.value in client.config.skip_categories:
                client.config.skip_categories.remove(opt.value)

        skips = ", ".join(client.config.skip_categories)
        await interaction.response.edit_message(
            content=f"Succesfully updated categories to skip to {skips}", view=None
        )
        self.view.stop()


class ChannelSelector(discord.ui.Select[discord.ui.View]):
    view: discord.ui.View

    def __init__(self, channels: dict[str, tuple[str, str]]) -> None:
        self.channels: dict[str, tuple[str, str]] = channels
        options = [
            discord.SelectOption(
                label=name.title(), value=_id, description=f"Subsribers: {subs}"
            )
            for _id, (name, subs) in channels.items()
        ]
        super().__init__(
            placeholder="Select the channel to whitelist",
            options=options,
            min_values=1,
            max_values=1,
        )

        self.selected: tuple[str, str] | None = None

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        selected = self.values[0]
        self.selected = (selected, self.channels[selected][0])
        self.view.stop()


@client.tree.command(name="change-state")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def change_state(  # noqa: PLR0911
    interaction: discord.Interaction, state: Literal["on", "off", "restart", "stop"]
) -> None:
    await interaction.response.defer()
    if state == "on":
        if client.app_is_running:
            await interaction.followup.send("App is already running")
            return

        await client.run_app()
        await interaction.followup.send("App started")
        return
    if state == "off":
        if not client.app_is_running:
            await interaction.followup.send("App is already stopped")
            return

        await client.close_app(off=True)
        await interaction.followup.send("App stopped")
        return
    if state == "restart":
        if not client.app_is_running:
            await interaction.followup.send("App is not running")
            return

        await client.close_app()
        await client.run_app()
        await interaction.followup.send("App restarted")
        return
    if state == "stop":
        await client.close_app(disconnect=True)
        await interaction.followup.send("App stopped and devices disconnected")
        return


@client.tree.command(name="change-skip-categories")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def change_category(
    interaction: discord.Interaction,
) -> None:
    view = discord.ui.View()
    slct = CategorySelector()
    view.add_item(slct)
    await interaction.response.send_message("Select the categories to skip", view=view)
    await view.wait()
    client.set_app_config()


@client.tree.command(name="change-settings")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def change_settings(
    interaction: discord.Interaction,
    *,
    api_key: str | None = None,
    skip_count_tracking: bool | None = None,
    mute_ads: bool | None = None,
    skip_ads: bool | None = None,
    autoplay: bool | None = None,
    handle_shorts: bool | None = None,
    device_name: str | None = None,
    minimum_skip_length: int | None = None,
) -> None:
    updated = ""
    if api_key is not None and api_key != client.config.apikey:
        client.config.apikey = api_key
        updated += f"API key updated from {client.config.apikey} to {api_key}\n"
    if skip_count_tracking is not None and str(skip_count_tracking) != str(
        client.config.skip_count_tracking
    ):
        client.config.skip_count_tracking = skip_count_tracking
        updated += f"Skip count tracking updated from {client.config.skip_count_tracking} to {skip_count_tracking}\n"
    if mute_ads is not None and str(mute_ads) != str(client.config.mute_ads):
        client.config.mute_ads = mute_ads
        updated += f"Mute ads updated from {client.config.mute_ads} to {mute_ads}\n"
    if skip_ads is not None and str(skip_ads) != str(client.config.skip_ads):
        updated += f"Skip ads updated from {client.config.skip_ads} to {skip_ads}\n"
        client.config.skip_ads = skip_ads
    if autoplay is not None and str(autoplay) != str(client.config.autoplay):
        updated += f"Autoplay updated from {client.config.autoplay} to {autoplay}\n"
        client.config.autoplay = autoplay
    if handle_shorts is not None and str(handle_shorts) != str(
        client.config.handle_shorts
    ):
        updated += f"Handle shorts updated from {client.config.handle_shorts} to {handle_shorts}\n"
        client.config.handle_shorts = handle_shorts
    if device_name is not None and device_name != client.config.device_name:
        updated += (
            f"Device name updated from {client.config.device_name} to {device_name}\n"
        )
        client.config.device_name = device_name
    if (
        minimum_skip_length is not None
        and minimum_skip_length != client.config.minimum_skip_length
    ):
        updated += f"Minimum skip length updated from {client.config.minimum_skip_length} to {minimum_skip_length}\n"
        client.config.minimum_skip_length = minimum_skip_length

    if not updated:
        await interaction.response.send_message("No settings updated")
        return

    client.set_app_config()
    await interaction.response.send_message(f"Settings updated\n\n{updated}")


@client.tree.command(name="get-settings")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def get_settings(interaction: discord.Interaction) -> None:
    emb = discord.Embed(title="Current settings")
    formatted_devices = ", ".join([
        f"{i.name} (ID: {i.screen_id})" for i in client.config.devices
    ])
    emb.description = (
        f"**Currently running:** {client.app_is_running}\n\n"
        f"**Devices:** {formatted_devices}\n"
        f"**API key:** {client.config.apikey}\n"
        f"**Skip count tracking:** {client.config.skip_count_tracking}\n"
        f"**Mute ads:** {client.config.mute_ads}\n"
        f"**Skip ads:** {client.config.skip_ads}\n"
        f"**Skip categories:** {', '.join(client.config.skip_categories)}\n"
        f"**Autoplay:** {client.config.autoplay}\n"
        f"**Handle shorts:** {client.config.handle_shorts}\n"
        f"**Device name:** {client.config.device_name}\n"
        f"**Channel whitelist:** {', '.join(client.whitelisted_channels.values()) or 'None'}"
        f"**Minimum skip length:** {client.config.minimum_skip_length}"
    )
    await interaction.response.send_message(embed=emb)


@client.tree.command(name="whitelist-channel")
@app_commands.allowed_contexts(
    guilds=True,
    dms=True,
)
@app_commands.allowed_installs(guilds=True, users=True)
async def whitelist_channel(
    interaction: discord.Interaction, name: str, channel_id: str | None = None
) -> None:
    if channel_id is not None:
        client.add_channel_whitelist(name, channel_id)
        client.set_app_config()
        await interaction.response.send_message(f"Channel {name} whitelisted!")
        return

    channels: list[tuple[str, str, int | str]] = await client.api_helper.search_channels(
        name
    )
    if not channels:
        await interaction.response.send_message("No channels found with that name")
        return

    if len(channels) == 1:
        _id, name, subs = channels[0]
        client.add_channel_whitelist(name, _id)
        client.set_app_config()
        await interaction.response.send_message(f"Channel {name} whitelisted!")
        return

    channel_dict = {cid: (cname, str(csubs)) for cid, cname, csubs in channels}
    view = discord.ui.View()
    slct = ChannelSelector(channel_dict)
    view.add_item(slct)

    await interaction.response.send_message("Select the channel to whitelist", view=view)
    await view.wait()

    if slct.selected is None:
        await interaction.followup.send("No channel selected")
        return

    _id, name = slct.selected
    client.add_channel_whitelist(name, _id)

    client.set_app_config()
    await interaction.followup.send(f"Channel {name} whitelisted!")


@client.tree.command(name="manage-video")
@app_commands.allowed_contexts(
    guilds=True,
    dms=True,
)
@app_commands.allowed_installs(guilds=True, users=True)
async def manage_video(
    interaction: discord.Interaction,
) -> None:
    await interaction.response.defer()
    device = client.devices[0]
    controller = device.controller
    video = controller.current_video
    if not video:
        await interaction.followup.send("No video playing")
        return

    video_id = video.video_id
    if not video_id:
        await interaction.followup.send("No id not found")
        return

    avideo = await client.api_helper.get_video_from_id(video_id)
    if not avideo:
        await interaction.followup.send("video not found")
        return

    view = VideoPlayer(avideo, controller)
    await interaction.followup.send(view=view, embed=view.embed)


class LogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        log = super().format(record)
        print(log)  # noqa: T201
        client.logs_sender.put(LogMessage(record, log))


signal.signal(signal.SIGINT, signal.SIG_DFL)


async def main() -> None:
    client.logs_sender.start()

    discord.utils.setup_logging(
        root=True,
        handler=LogHandler(),
        formatter=discord.utils._ColourFormatter(),
    )
    await client.start(client.config.discord_bot_token)


asyncio.run(main())
