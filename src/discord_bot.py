from __future__ import annotations

import asyncio
import logging
import os
import signal
from typing import Any, Literal

import aiohttp
import discord
import pyytlounge
import pyytlounge.exceptions
from discord import app_commands
from dotenv import load_dotenv

from iSponsorBlockTV import APIHelper, Config, Device, DeviceManager
from video_player import VideoPlayer

load_dotenv()


_log = logging.getLogger(__file__.split(os.sep)[-1].split(".")[0])


class BlockBotClient(discord.Client):
    tcp_connector: aiohttp.TCPConnector
    web_session: aiohttp.ClientSession
    api_helper: APIHelper
    config: Config

    def __init__(self) -> None:
        super().__init__(intents=discord.Intents.none())

        self.tree = app_commands.CommandTree(self)

        self.devices: list[DeviceManager] = []
        self.tasks: set[asyncio.Task[Any]] = set()

        self.whitelisted_channels: dict[str, str] = {}

        self.app_is_running: bool = False
        self.logs_webhook: discord.SyncWebhook = discord.SyncWebhook.from_url(
            "https://canary.discord.com/api/webhooks/1295860248921247804/z8gMrY9qITCJ8TFqNcS7a9uH0ruqBcNMzfhdJHPJqCIAX75ht11-7RLbeb_QyDIV5Iyf",
        )

        self.video_channel: discord.TextChannel | None = None

    def purge_all_video_messages(self) -> None:
        async def purge() -> None:
            if self.video_channel:
                channel = self.video_channel
            else:
                channel: discord.TextChannel = await self.fetch_channel(self.config.current_video_webhook["channel_id"])  # type: ignore
                self.video_channel = channel  # type: ignore

            await channel.purge(limit=None, check=lambda m: m.id != self.api_helper._current_video_message_id)  # type: ignore

        self.create_task(purge())

    def create_task(self, coro: Any) -> asyncio.Task:
        task = asyncio.create_task(coro)
        task.add_done_callback(lambda fut: self.tasks.discard(fut))
        self.tasks.add(task)
        return task

    def set_app_config(self) -> None:
        self.config = Config("data/config.json")

        self.whitelisted_channels = {
            c["id"]: c["name"] for c in self.config.channel_whitelist
        }

    def save_app_config(self) -> None:
        self.config.channel_whitelist = [
            {"id": _id, "name": name} for _id, name in self.whitelisted_channels.items()
        ]
        self.config.save()
        self.set_app_config()

    async def run_app(self) -> None:
        self.tcp_connector = aiohttp.TCPConnector(ttl_dns_cache=300)
        self.web_session = aiohttp.ClientSession(connector=self.tcp_connector)
        self.api_helper = APIHelper(
            config=self.config, web_session=self.web_session, discord_client=self
        )

        cdevice: Device
        for cdevice in self.config.devices:
            device = DeviceManager(
                cdevice,
                api_helper=self.api_helper,
                debug=True,
            )
            self.create_task(device.start())
            self.devices.append(device)

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

    async def setup_hook(self) -> None:
        self.set_app_config()
        _log.info(f"Logged in as {self.user}")

        self.create_task(self.run_app())

        # await self.sync_commands()

    async def close_app(self, disconnect: bool = False, off: bool = False) -> None:
        try:
            _log.info("Closing devices, disconnect? %s", disconnect)
            for device in self.devices:
                _log.info("Closing device %s", device.device.name)

                _log.info("Closing device")
                try:
                    await device.close()
                except Exception as e:
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
                        pass
                    except Exception as e:
                        _log.error("Error disconnecting device: %s", exc_info=e)
                    else:
                        _log.info("Device disconnected")

            _log.info("Closing web session %s", self.web_session)
            try:
                await self.web_session.close()
            except Exception as e:
                _log.error("Error closing web session: %s", exc_info=e)
            else:
                _log.info("Web session closed")

        except Exception as e:
            _log.error(f"Error closing app: {e}", exc_info=e)
            pass

        self.app_is_running = False
        self.devices = []

        for task in self.tasks:
            try:
                task.cancel()
            except Exception:
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


class CategorySelector(discord.ui.Select):
    def __init__(self):
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
        self.view.stop()  # type: ignore


class ChannelSelector(discord.ui.Select[discord.ui.View]):
    view: discord.ui.View  # type: ignore

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
    client.save_app_config()


@client.tree.command(name="change-settings")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def change_settings(
    interaction: discord.Interaction,
    api_key: str | None = None,
    skip_count_tracking: bool | None = None,
    mute_ads: bool | None = None,
    skip_ads: bool | None = None,
    autoplay: bool | None = None,
    handle_shorts: bool | None = None,
    device_name: str | None = None,
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

    if not updated:
        await interaction.response.send_message("No settings updated")
        return

    client.save_app_config()
    await interaction.response.send_message(f"Settings updated\n\n{updated}")


@client.tree.command(name="get-settings")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.allowed_installs(guilds=True, users=True)
async def get_settings(interaction: discord.Interaction):
    emb = discord.Embed(title="Current settings")
    formatted_devices = ", ".join(
        [f"{i.name} (ID: {i.screen_id})" for i in client.config.devices]
    )
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
    )
    await interaction.response.send_message(embed=emb)


@client.tree.command(name="whitelist-channel")
@app_commands.allowed_contexts(
    guilds=True,
    dms=True,
)
@app_commands.allowed_installs(guilds=True, users=True)
async def whitelist_channel(
    interaction: discord.Interaction, name: str, id: str | None = None
):
    if id is not None:
        client.add_channel_whitelist(name, id)
        client.save_app_config()
        await interaction.response.send_message(f"Channel {name} whitelisted!")
        return

    channels: list[tuple[str, str, int | str]] = (
        await client.api_helper.search_channels(name)
    )
    print("channels", channels)
    if not channels:
        await interaction.response.send_message("No channels found with that name")
        return

    if len(channels) == 1:
        _id, name, subs = channels[0]
        client.add_channel_whitelist(name, _id)
        client.save_app_config()
        await interaction.response.send_message(f"Channel {name} whitelisted!")
        return

    channel_dict = {cid: (cname, str(csubs)) for cid, cname, csubs in channels}
    view = discord.ui.View()
    slct = ChannelSelector(channel_dict)
    view.add_item(slct)

    await interaction.response.send_message(
        "Select the channel to whitelist", view=view
    )
    await view.wait()

    if slct.selected is None:
        await interaction.followup.send("No channel selected")
        return

    _id, name = slct.selected
    client.add_channel_whitelist(name, _id)

    client.save_app_config()
    await interaction.followup.send(f"Channel {name} whitelisted!")


@client.tree.command(name="manage-video")
@app_commands.allowed_contexts(
    guilds=True,
    dms=True,
)
@app_commands.allowed_installs(guilds=True, users=True)
async def manage_video(
    interaction: discord.Interaction,
):
    await interaction.response.defer()
    device = client.devices[0]
    controller = device.controller
    video = controller.current_video
    print("video", video, device, controller)
    if not video:
        await interaction.followup.send("No video playing")
        return

    video_id = video.video_id
    print("video_id", video_id)
    if not video_id:
        await interaction.followup.send("No id not found")
        return

    avideo = await client.api_helper.get_video_from_id(video_id)
    print("avideo", avideo)
    if not avideo:
        await interaction.followup.send("video not found")
        return

    view = VideoPlayer(avideo, controller)
    await interaction.followup.send(view=view, embed=view.embed)


class LogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        log = super().format(record)
        log_prefix = ""
        embed_color = discord.Color.dark_theme()
        if record.levelno == logging.INFO:
            log_prefix = "ℹ️ **INFO**"  # noqa: RUF001
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
        # message_without_cb = f"{log_prefix} - {created}\n{log}"
        print(log)  # noqa: T201
        emb = discord.Embed(
            title=f"{log_prefix} - {created}",
            description=f"```ansi\n{log}\n```",
            color=embed_color,
        )
        client.logs_webhook.send(embed=emb)


signal.signal(signal.SIGINT, signal.SIG_DFL)
client.run(TOKEN, root_logger=True, log_handler=LogHandler(), log_formatter=discord.utils._ColourFormatter())  # type: ignore
