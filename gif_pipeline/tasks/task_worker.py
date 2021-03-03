import asyncio
from typing import List, Awaitable

from gif_pipeline.tasks.task import Task, T


class Bottleneck:

    def __init__(self, num_concurrent: int):
        self.num_concurrent = num_concurrent
        self.semaphore = asyncio.Semaphore(num_concurrent)

    async def await_run(self, awaitable: Awaitable[T]) -> T:
        async with self.semaphore:
            return await awaitable


class TaskWorker(Bottleneck):

    async def await_task(self, task: Task[T]) -> T:
        return await self.await_run(task.run())

    async def await_tasks(self, tasks: List[Task]):
        return await asyncio.gather(*[self.await_task(task) for task in tasks])
