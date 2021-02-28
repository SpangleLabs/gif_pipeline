import asyncio
from typing import List

from gif_pipeline.tasks.task import Task, T


class TaskWorker:

    def __init__(self, num_concurrent):
        self.num_concurrent = num_concurrent
        self.semaphore = asyncio.Semaphore(num_concurrent)

    async def await_task(self, task: Task[T]) -> T:
        async with self.semaphore:
            return await task.run()

    async def await_tasks(self, tasks: List[Task]):
        return await asyncio.gather(*[self.await_task(task) for task in tasks])
