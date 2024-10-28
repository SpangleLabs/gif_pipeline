import asyncio
import logging
from typing import List, Awaitable

from prometheus_client import Gauge

from gif_pipeline.tasks.task import Task, T

worker_queue_length = Gauge(
    "gif_pipeline_taskworker_tasks_in_progress",
    "Number of tasks currently in progress"
)

logger = logging.getLogger(__name__)


class Bottleneck:

    def __init__(self, num_concurrent: int):
        self.num_concurrent = num_concurrent
        self.semaphore = asyncio.Semaphore(num_concurrent)

    async def await_run(self, awaitable: Awaitable[T]) -> T:
        async with self.semaphore:
            return await awaitable


class TaskWorker(Bottleneck):

    def __init__(self, num_concurrent: int):
        super().__init__(num_concurrent)
        self.current_tasks: List[T] = []
        self.task_watch_lock = asyncio.Lock()

    def _log_tasks(self) -> None:
        task_lines = ["\n" + repr(task) for task in self.current_tasks]
        logger.debug("TaskWorker current tasks (%s):\n%s", len(task_lines), "".join(task_lines))

    async def _pre_task(self, task: Task[T]) -> None:
        async with self.task_watch_lock:
            self.current_tasks.append(task)
            self._log_tasks()
            logger.debug("Starting task: %s", task)

    async def _post_task(self, task: Task[T]) -> None:
        async with self.task_watch_lock:
            self.current_tasks.remove(task)
            self._log_tasks()
            logger.debug("Finished task: %s", task)

    async def _run_task(self, task: Task[T]) -> T:
        await self._pre_task(task)
        try:
            resp = await task.run()
            return resp
        finally:
            await self._post_task(task)

    async def await_task(self, task: Task[T]) -> T:
        with worker_queue_length.track_inprogress():
            return await self.await_run(self._run_task(task))

    async def await_tasks(self, tasks: List[Task]):
        return await asyncio.gather(*[self.await_task(task) for task in tasks])
