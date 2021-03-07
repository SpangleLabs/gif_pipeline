import logging
import os
import shutil
from abc import abstractmethod, ABC
from typing import List, Awaitable

from tqdm import tqdm

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat
from gif_pipeline.chat_data import ChatData, ChannelData, WorkshopData
from gif_pipeline.chat_config import ChatConfig
from gif_pipeline.message import Message
from gif_pipeline.tasks.task_worker import Bottleneck
from gif_pipeline.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


class ChatBuilder(ABC):
    chat_type = "chat"

    def __init__(self, database: Database, client: TelegramClient, download_bottleneck: Bottleneck):
        self.database = database
        self.client = client
        self.download_bottleneck = download_bottleneck

    @abstractmethod
    def list_chats(self) -> List[ChatData]:
        pass

    def delete_chats(self, chats: List[ChatData]) -> None:
        for chat in tqdm(chats, desc=f"Deleting excess {self.chat_type}s"):
            messages = self.database.list_messages_for_chat(chat)
            for message in tqdm(messages, position=1, desc=f"Removing {chat.title} messages"):
                self.database.remove_message(message)
            self.database.remove_chat(chat)
            # Clear files
            shutil.rmtree(chat.directory, ignore_errors=True)

    @abstractmethod
    async def create_chat_data(self, chat_config: ChatConfig) -> ChatData:
        pass

    async def get_chat_data(self, chat_confs: List[ChatConfig]) -> List[ChatData]:
        db_data = self.list_chats()
        chat_data_list = []
        logger.info(f"Creating {self.chat_type} data")
        for conf in tqdm(chat_confs, desc=f"Creating {self.chat_type} data"):
            matching_chat_data = next(
                (chat for chat in db_data if chat.username == conf.handle or chat.chat_id == conf.handle),
                None
            )
            if matching_chat_data:
                chat_data_list.append(matching_chat_data)
                db_data.remove(matching_chat_data)
            else:
                chat_data = await self.create_chat_data(conf)
                chat_data_list.append(chat_data)
                self.database.save_chat(chat_data)
                os.makedirs(chat_data.directory, exist_ok=True)
        logger.info(f"Deleting {self.chat_type}s")
        self.delete_chats(db_data)
        return chat_data_list

    async def get_message_inits(
            self,
            chat_confs: List[ChatConfig],
            chat_data_list: List[ChatData]
    ) -> List[List[Awaitable[Message]]]:
        message_inits = []
        total = len(chat_confs)
        title = f"Listing {self.chat_type} messages"
        for chat_conf, chat_data in tqdm(zip(chat_confs, chat_data_list), title, total=total):
            new_inits = [
                self.download_bottleneck.await_run(message_init)
                for message_init
                in await Chat.list_message_initialisers(chat_data, chat_conf, self.client, self.database)
            ]
            message_inits.append(new_inits)
        return message_inits


class ChannelBuilder(ChatBuilder):
    chat_type = "channel"

    def list_chats(self) -> List[ChatData]:
        return self.database.list_channels()

    async def create_chat_data(self, chat_config: ChatConfig) -> ChannelData:
        return await self.client.get_channel_data(chat_config.handle)


class WorkshopBuilder(ChatBuilder):
    chat_type = "workshop"

    def list_chats(self) -> List[ChatData]:
        return self.database.list_workshops()

    async def create_chat_data(self, chat_config: ChatConfig) -> WorkshopData:
        return await self.client.get_workshop_data(chat_config.handle)
