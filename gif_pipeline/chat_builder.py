import logging
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
    def __init__(self, database: Database, client: TelegramClient, download_bottleneck: Bottleneck):
        self.database = database
        self.client = client
        self.download_bottleneck = download_bottleneck

    @abstractmethod
    def list_chats(self) -> List[ChatData]:
        pass

    def delete_chats(self, chats: List[ChatData]) -> None:
        for chat in tqdm(chats, desc="Deleting excess chats"):
            messages = self.database.list_messages_for_chat(chat)
            for message in tqdm(messages, position=1, desc="Removing messages"):
                self.database.remove_message(message)
            self.database.remove_chat(chat)
            # Clear files
            shutil.rmtree(chat.directory, ignore_errors=True)

    @abstractmethod
    async def create_chat_data(self, chat_config: ChatConfig) -> ChatData:
        pass

    async def get_chat_data(self, chat_confs: List[ChatConfig]) -> List[ChatData]:
        db_data = self.list_chats()
        chat_data = []
        logger.info("Creating chat data")
        for conf in tqdm(chat_confs, desc="Creating chat data"):
            matching_chat_data = next(
                (chat for chat in db_data if chat.username == conf.handle or chat.chat_id == conf.handle),
                None
            )
            if matching_chat_data:
                chat_data.append(matching_chat_data)
                db_data.remove(matching_chat_data)
            else:
                chat_data.append(await self.create_chat_data(conf))
        logger.info("Deleting chats")
        self.delete_chats(db_data)
        return chat_data

    async def get_message_inits(
            self,
            chat_confs: List[ChatConfig],
            chat_data_list: List[ChatData]
    ) -> List[List[Awaitable[Message]]]:
        message_inits = []
        for chat_conf, chat_data in tqdm(zip(chat_confs, chat_data_list), "Listing messages"):
            new_inits = [
                self.download_bottleneck.await_run(message_init)
                for message_init
                in await Chat.list_message_initialisers(chat_data, chat_conf, self.client, self.database)
            ]
            message_inits.append(new_inits)
        return message_inits


class ChannelBuilder(ChatBuilder):

    def list_chats(self) -> List[ChatData]:
        return self.database.list_channels()

    async def create_chat_data(self, chat_config: ChatConfig) -> ChannelData:
        return await Chat.create_chat_data(self.client.get_channel_data, chat_config, self.database)


class WorkshopBuilder(ChatBuilder):

    def list_chats(self) -> List[ChatData]:
        return self.database.list_workshops()

    async def create_chat_data(self, chat_config: ChatConfig) -> WorkshopData:
        return await Chat.create_chat_data(self.client.get_workshop_data, chat_config, self.database)
