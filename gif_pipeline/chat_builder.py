from abc import abstractmethod, ABC
from typing import List, Awaitable

from tqdm import tqdm

from gif_pipeline.database import Database
from gif_pipeline.group import ChatData, ChatConfig, Group, Channel, WorkshopGroup
from gif_pipeline.telegram_client import TelegramClient


class ChatBuilder(ABC):
    def __init__(self, database: Database, client: TelegramClient):
        self.database = database
        self.client = client

    @abstractmethod
    def list_chats(self) -> List[ChatData]:
        pass

    def delete_chats(self, chats: List[ChatData]) -> None:
        for chat in chats:
            messages = self.database.list_messages_for_chat(chat)
            for message in tqdm(messages):
                self.database.remove_message(message)
            self.database.remove_chat(chat)

    @abstractmethod
    async def create_chat(self, chat_config: ChatConfig) -> Group:
        pass

    @abstractmethod
    async def update_chat(self, chat_config: ChatConfig, chat_data: ChatData) -> Group:
        pass

    def get_initialisers(self, chat_confs: List[ChatConfig]) -> List[Awaitable[Group]]:
        chat_data = self.list_chats()
        init_tasks = []
        for conf in chat_confs:
            matching_chat_data = next(
                (chat for chat in chat_data if chat.username == conf.handle or chat.chat_id == conf.handle),
                None
            )
            if matching_chat_data:
                chat_data.remove(matching_chat_data)
                init_tasks.append(self.update_chat(conf, matching_chat_data))
            else:
                init_tasks.append(self.create_chat(conf))
        self.delete_chats(chat_data)
        return init_tasks


class ChannelBuilder(ChatBuilder):

    def list_chats(self) -> List[ChatData]:
        return self.database.list_channels()

    async def create_chat(self, chat_config: ChatConfig) -> Group:
        return await Channel.from_config(chat_config, self.client, self.database)

    async def update_chat(self, chat_config: ChatConfig, chat_data: ChatData) -> Group:
        return await Channel.from_data(chat_data, chat_config, self.client, self.database)


class WorkshopBuilder(ChatBuilder):

    def list_chats(self) -> List[ChatData]:
        return self.database.list_workshops()

    async def create_chat(self, chat_config: ChatConfig) -> Group:
        return await WorkshopGroup.from_config(chat_config, self.client, self.database)

    async def update_chat(self, chat_config: ChatConfig, chat_data: ChatData) -> Group:
        return await WorkshopGroup.from_data(chat_data, chat_config, self.client, self.database)