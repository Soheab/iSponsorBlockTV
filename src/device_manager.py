from __future__ import annotations
from typing import TYPE_CHECKING, Any, NoReturn, TypedDict

import time
import asyncio
import logging
from functools import cached_property

from .lounge import LoungeAPI

if TYPE_CHECKING:
    from .api_helper import APIHelper

__all__ = (
    "Device",
    "DeviceManager",
)


class DeviceConfig(TypedDict):
    name: str
    screen_id: str
    offset: float | int


class Device:
    def __init__(self, data: DeviceConfig) -> None:
        self.name: str = data["name"]
        self.screen_id: str = data["screen_id"]
        # Change offset to seconds (from milliseconds)
        self.offset: float = int(data["offset"]) / 1000

        if not self.screen_id:
            msg = "No screen id found"
            raise ValueError(msg)

    def __repr__(self) -> str:
        return f"<Device {self.name} ({self.screen_id})>"
    
    def _asdict(self) -> DeviceConfig:
        return {
            "name": self.name,
            "screen_id": self.screen_id,
            "offset": self.offset,
        }

    async def connect(
        self,
        api_helper: APIHelper,
        debug: bool,
    ) -> DeviceManager:
        inst = DeviceManager(self, api_helper, debug)
        await inst.start()
        return inst


class DeviceManager:
    def __init__(
        self,
        device: Device,
        /,
        api_helper: APIHelper,
        debug: bool,
    ) -> None:
        self.device: Device = device
        self.api_helper: APIHelper = api_helper
        self.debug: bool = debug
        self.cancelled: bool = False

        if debug:
            self.logger.setLevel(logging.DEBUG)
        else:
            self.logger.setLevel(logging.INFO)

        sh = logging.StreamHandler()
        sh.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        self.logger.addHandler(sh)
        self.logger.info(f"Starting device manager for {self.device}")

        self.main_task: asyncio.Task | None = None
        self.controller: LoungeAPI = LoungeAPI(api_helper)

    @cached_property
    def logger(self) -> logging.Logger:
        return logging.getLogger(f"iSponsorBlockTV-{self.device.screen_id}")

    # async def wait_for_shorts(self):
    #    print("Waiting for shorts called")
    #    controller = self.controller
    #    while controller.current_video and controller.shorts_disconnected:
    #        print("Waiting for shorts TO END")
    #        await asyncio.sleep(1)
    #        has_ended = controller.current_video.has_ended
    #        print(f"has_ended: {has_ended}")
    #        if has_ended:
    #            print("Shorts has ended")
    #            controller.shorts_disconnected = False
    #            await self.start()

    # Method called on playback state change
    async def __call__(self, state: Any) -> None:
        if self.main_task:
            try:
                self.main_task.cancel()
            except:  # noqa: S110
                pass

        time_start = time.time()
        self.main_task = self.api_helper.create_task(
            self.process_playstatus(state, time_start)
        )

    async def start(self) -> None:
        await self.controller.pair_with_screen_id(
            screen_id=self.device.screen_id,
            screen_name=self.device.name,
        )

        self.api_helper.create_task(self.loop())
        self.api_helper.create_task(self.refresh_auth_loop())
        # self.api_helper.create_task(self.wait_for_shorts())

    async def loop(self) -> None:
        lounge_controller = self.controller

        while not self.cancelled:
            # if self.controller.shorts_disconnected:
            #     await self.close()
            #     print("Shorts disconnected", self.controller.shorts_disconnected, self.controller.current_video)
            #     while self.controller.current_video and self.controller.shorts_disconnected:
            #         print("Waiting for shorts TO END")
            #         await asyncio.sleep(1)
            #         has_ended = self.controller.current_video.has_ended
            #         print(f"has_ended: {has_ended}")
            #         if has_ended:
            #             print("Shorts has ended")
            #             self.controller.shorts_disconnected = False
            #             await self.start()

            while not lounge_controller.linked():
                try:
                    self.logger.debug("Refreshing auth")
                    await lounge_controller.refresh_auth()
                except:  # Exception as e:
                    # self.logger.error("Error refreshing auth: %s. Trying again in 10 seconds.", e)
                    # raceback.print_exc()
                    await asyncio.sleep(10)

            while not (await self.is_available()) and not self.cancelled:
                await asyncio.sleep(10)

            try:
                await lounge_controller.connect()
            except Exception as e:
                self.logger.exception("Error connecting to device: %s.", exc_info=e)
            while not lounge_controller.connected() and not self.cancelled:
                # Doesn't connect to the device if it's a kids profile (it's broken)
                await asyncio.sleep(10)
                try:
                    await lounge_controller.connect()
                except:  # Exception as e:  # noqa: S110
                    # self.logger.error("Error connecting to device: %s.", e)
                    pass

            self.logger.info(
                "Connected to device %s (%s)",
                lounge_controller.screen_name,
                self.device.name,
            )
            try:
                self.logger.info("Subscribing to lounge")
                sub = await lounge_controller.subscribe_monitored(self)
                await sub
            except Exception as e:
                self.logger.exception("Error subscribing to lounge.", exc_info=e)

    # Ensures that we have a valid auth token
    async def refresh_auth_loop(self) -> NoReturn:
        while True:
            await asyncio.sleep(60 * 60 * 24)  # Refresh every 24 hours
            try:
                await self.controller.refresh_auth()
            except Exception as e:
                self.logger.exception("Error refreshing auth.", exc_info=e)
                # traceback.print_exc()

    async def is_available(self) -> bool:
        try:
            return await self.controller.is_available()
        except:  # Exception as e:
            # self.logger.error("Error checking if device is available: %s.", e)
            return False

    # Processes the playback state change
    async def process_playstatus(self, state: Any, time_start: Any) -> None:
        segments = []
        if state.videoId:
            segments = await self.api_helper.get_segments(state.videoId)
        # print("Segments:", segments)
        if state.state.value == 1:  # Playing
            self.logger.info(
                f"Playing video {state.videoId} with {len(segments)} segments"
            )
            if segments:  # If there are segments
                await self.time_to_segment(
                    segments, state.currentTime, time_start
                )  # Skip to the next segment

    # Finds the next segment to skip to and skips to it
    async def time_to_segment(
        self, segments: list[Any], position: int, time_start: float
    ) -> None:
        start_next_segment = None
        next_segment = None
        for segment in segments:
            if position < 2 and (segment["start"] <= position < segment["end"]):
                next_segment = segment
                start_next_segment = (
                    position  # different variable so segment doesn't change
                )
                break
            if segment["start"] > position:
                next_segment = segment
                start_next_segment = next_segment["start"]
                break
        if start_next_segment:
            time_to_next = (
                start_next_segment
                - position
                - (time.time() - time_start)
                - self.device.offset
            )

            if next_segment and next_segment:
                await self.skip(time_to_next, next_segment["end"], next_segment["UUID"])

    # Skips to the next segment (waits for the time to pass)
    async def skip(self, time_to, position, uuids):
        logging.info("Skipping segment: seeking to %s in %s seconds", position, time_to)
        await asyncio.sleep(time_to)
        self.logger.info("Skipping segment: seeking to %s", position)
        await self.api_helper.mark_viewed_segments(uuids)
        await self.controller.seek_to(position)

    async def close(self) -> None:
        self.cancelled = True
        if self.main_task:
            try:
                await asyncio.sleep(1)
                self.main_task.cancel()
            except Exception:  # noqa: BLE001, S110
                pass

        await self.controller.close()
