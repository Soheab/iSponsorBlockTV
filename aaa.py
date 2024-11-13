import datetime
import random
import string
import sys
import time
from src.iSponsorBlockTV.simple_async_cache import ExpiryCache

import asyncio
from src.iSponsorBlockTV.sinbad_cache import lrutaskcache


class HeavyObject:
    def __init__(self, size):
        self.data = [i for i in range(size)]

    def compute(self):
        return sum(self.data)


def O(size):
    obj = HeavyObject(size)
    return obj.compute()

async def lol(v):
    return "lol{}".format(v)
    



@lrutaskcache(300, maxsize=10)
async def with_cache(vid_id: str) -> int:
    return vid_id


async def without_cache(vid_id: str):
    result = 0
    for char in vid_id:
        result += O(ord(char))
    return result


class InClass:
    @ExpiryCache.wrap_async(datetime.timedelta(seconds=1), maxsize=3)
    async def with_cache(self, vid_id: str) -> int:
        result = 0
        for char in vid_id:
            result += O(ord(char))
        return result


main_video_id = "".join(random.choices(string.ascii_letters + string.digits, k=10))
video_ids = [
    "".join(random.choices(string.ascii_letters + string.digits, k=10))
    for _ in range(10)
]
for _ in range(10):
    video_ids.insert(random.randint(0, len(video_ids)), main_video_id)

inst = InClass()


async def main():
    cache_before = time.time()

    for _ in range(100):
        # await inst.with_cache(random.choice(video_ids))
        await with_cache([main_video_id])

    cache_after = time.time()

    cache_diff = cache_after - cache_before
    print(f"Cache time: {cache_diff}")

    no_cache_before = time.time()
    for _ in range(100):
        await without_cache(vid_id=random.choice(video_ids))
    no_cache_after = time.time()

    no_cache_diff = no_cache_after - no_cache_before
    print(f"No cache time: {no_cache_diff}")

    faster = "Cache" if cache_diff < no_cache_diff else "No cache"
    if cache_diff == no_cache_diff:
        faster = "Neither"

    print(f"{faster} is faster")

    # print("\n".join(vals))


async def runner():
    val = with_cache(main_video_id)
    for _ in range(10):
        print(val)
        print(await val)
        print(f"Run {_ + 1}:")


asyncio.run(runner())
