"""Send out an M-SEARCH request and listen for responses.

Modified code from
https://github.com/codingjoe/ssdp/blob/main/ssdp/__main__.py
"""

from typing import Any

import socket
import asyncio

import ssdp
from ssdp import network
import aiohttp
import xmltodict


class Handler(ssdp.aio.SSDP):
    """Handler for SSDP responses."""

    def __init__(self) -> None:
        super().__init__()
        self.devices: list[str] = []

    def clear(self) -> None:
        """Clear the list of devices."""
        self.devices = []

    def __call__(self) -> "Handler":
        return self

    def response_received(
        self, response: ssdp.messages.SSDPResponse, addr: Any
    ) -> None:
        """Handle received SSDP responses."""
        location = next(
            (v for k, v in response.headers if k.lower() == "location"), None
        )
        if location:
            self.devices.append(location)


class DialClient:
    """DIAL client."""

    def __init__(self, web_session: aiohttp.ClientSession) -> None:
        self.web_session: aiohttp.ClientSession = web_session

    @staticmethod
    def _validate_pairing_code(pairing_code: str) -> bool:
        """Validate the pairing code."""
        cleaned_code = pairing_code.replace("-", "").replace(" ", "")
        return cleaned_code.isdigit() and len(cleaned_code) == 12

    @staticmethod
    def get_ip() -> str:
        """Get the local IP address."""
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(0)
            try:
                s.connect(("10.254.254.254", 1))
                ip = s.getsockname()[0]
            except Exception:  # noqa: BLE001
                ip = "127.0.0.1"
        return ip

    async def find_youtube_app(self, url_location: str) -> dict[str, Any]:
        """Find the YouTube app on a device."""
        async with self.web_session.get(url_location) as url_res:
            if url_res.status != 200:
                return {}

            headers = url_res.headers
            location_response: str = await url_res.text()

            data: dict[str, Any] = xmltodict.parse(location_response)
            name = data["root"]["device"]["friendlyName"]
            app_url = headers.get("Application-URL")
            if not app_url:
                return {}

            youtube_url: str = f"{app_url}YouTube"
            async with self.web_session.get(youtube_url) as res:
                if res.status == 200:
                    data = xmltodict.parse(await res.text())
                    screen_id = data["service"]["additionalData"]["screenId"]
                    return {"screen_id": screen_id, "name": name, "offset": 0}

            return {}

    async def discover(self) -> list[dict[str, Any]]:
        """Discover devices on the network."""
        bind = None
        search_target = "urn:dial-multiscreen-org:service:dial:1"
        max_wait = 10
        handler = Handler()

        family, _addr = (
            network.get_best_family(  # pyright: ignore[reportUnknownMemberType]
                bind, network.PORT
            )
        )
        loop = asyncio.get_event_loop()
        ip_address = self.get_ip()
        connect = loop.create_datagram_endpoint(
            handler,
            family=family,
            local_addr=(ip_address, None),  # pyright: ignore[reportArgumentType]
        )
        transport, _protocol = await connect

        target = (network.MULTICAST_ADDRESS_IPV4, network.PORT)

        search_request = ssdp.messages.SSDPRequest(
            "M-SEARCH",
            headers={
                "HOST": f"{target[0]}:{target[1]}",
                "MAN": '"ssdp:discover"',
                "MX": str(max_wait),  # seconds to delay response [1..5]
                "ST": search_target,
            },
        )

        search_request.sendto(transport, target)

        try:
            await asyncio.sleep(4)
        finally:
            transport.close()

        devices = await asyncio.gather(
            *(self.find_youtube_app(location) for location in handler.devices)
        )
        return [device for device in devices if device]

    async def discover_devices(self) -> list[dict[str, Any]]:
        """Discover devices and return their information."""
        return await self.discover()
