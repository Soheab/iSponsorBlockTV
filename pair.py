import asyncio

import aiohttp

from src.dial_client import DialClient


async def main() -> None:
    async with aiohttp.ClientSession() as session:
        client = DialClient(session)
        devices = await client.discover_devices()
        for device in devices:
            print(device)


asyncio.run(main())
