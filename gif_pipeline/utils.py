import asyncio
from typing import Awaitable, List, TypeVar

from tqdm import tqdm

T = TypeVar("T")


async def tqdm_gather(awaitables: List[Awaitable[T]], **kwargs) -> List[T]:
    async def wrap_awaitable(number: int, awaitable: Awaitable[T]):
        return number, await awaitable

    numbered_awaitables = [wrap_awaitable(idx, awaitables[idx]) for idx in range(len(awaitables))]

    numbered_results = [
        await f for f in tqdm(asyncio.as_completed(numbered_awaitables), total=len(awaitables), **kwargs)
    ]

    results = [result_tuple[1] for result_tuple in sorted(numbered_results)]

    return results
