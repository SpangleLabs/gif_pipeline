import asyncio
from typing import Awaitable, List, TYPE_CHECKING

from prometheus_client import Gauge

if TYPE_CHECKING:
    from gif_pipeline.tasks.task import T, Task

worker_queue_length = Gauge("gif_pipeline_taskworker_tasks_in_progress", "Number of tasks currently in progress")


class Bottleneck:
    def __init__(self, num_concurrent: int):
        self.num_concurrent = num_concurrent
        self.semaphore = asyncio.Semaphore(num_concurrent)

    async def await_run(self, awaitable: Awaitable[T]) -> T:
        async with self.semaphore:
            return await awaitable


class TaskWorker(Bottleneck):
    async def await_task(self, task: Task[T]) -> T:
        with worker_queue_length.track_inprogress():
            return await self.await_run(task.run())

    async def await_tasks(self, tasks: List[Task]):
        return await asyncio.gather(*[self.await_task(task) for task in tasks])
