from abc import ABC, abstractmethod
from typing import Optional, List

from telethon.tl.types import Message

from gif_pipeline.database import Database
from gif_pipeline.message import MessageData
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class PublicHelper(ABC):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        self.database = database
        self.client = client
        self.worker = worker

    @abstractmethod
    async def on_new_message(self, message: Message) -> Optional[List[MessageData]]:
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__
