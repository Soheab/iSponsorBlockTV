import asyncio

import aiohttp

from src.dial_client import discover


async def main():
    async with aiohttp.ClientSession() as session:
        devices = await discover(session)
        print(f"devices: {devices}")


asyncio.run(main())
