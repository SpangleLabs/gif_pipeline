from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from typing import Dict, Union, Any, TypeVar, List, Optional, Coroutine, Callable
from typing import TYPE_CHECKING

from message import Message

if TYPE_CHECKING:
    from telegram_client import TelegramClient
    from database import Database
    from message import MessageData
T = TypeVar('T', bound='Group')
C = TypeVar('C', bound='ChatData')


class ChatConfig(ABC):
    def __init__(self, handle: Union[str, int], queue: bool = False):
        self.handle = handle
        self.queue = queue

    @staticmethod
    @abstractmethod
    def from_json(json_dict: Dict[str, Any]) -> 'ChatConfig':
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(handle={self.handle})"


class ChannelConfig(ChatConfig):

    @staticmethod
    def from_json(json_dict) -> 'ChannelConfig':
        return ChannelConfig(json_dict['handle'], json_dict['queue'])


class WorkshopConfig(ChatConfig):

    @staticmethod
    def from_json(json_dict) -> 'WorkshopConfig':
        return WorkshopConfig(json_dict['handle'])


class ChatData(ABC):
    def __init__(self, chat_id: int, username: Optional[str], title: str) -> None:
        self.chat_id = chat_id
        self.username = username
        self.title = title

    @property
    @abstractmethod
    def directory(self) -> str:
        pass

    @abstractmethod
    def telegram_link_for_message(self, message_data: 'MessageData') -> str:
        pass


class ChannelData(ChatData):

    @property
    def directory(self) -> str:
        return f"store/channels/{self.username}/"

    def telegram_link_for_message(self, message_data: 'MessageData') -> str:
        return f"https://t.me/{self.username}/{message_data.message_id}"


class WorkshopData(ChatData):

    @property
    def directory(self) -> str:
        return f"store/workshop/{self.chat_id}/"

    def telegram_link_for_message(self, message_data: 'MessageData') -> str:
        handle = abs(self.chat_id)
        return f"https://t.me/c/{handle}/{message_data.message_id}"


class Group(ABC):
    def __init__(
            self,
            chat_data: ChatData,
            queue: bool,
            messages: List[Message],
            client: TelegramClient
    ):
        self.chat_data = chat_data
        self.queue = queue
        self.messages = messages
        self.client = client

    @staticmethod
    async def load_chat_data(
            getter: Callable[[str], Coroutine[None, None, C]],
            config: 'ChatConfig',
            client: TelegramClient,
            database: 'Database'
    ) -> C:
        # Get chat id, name, etc
        chat_data = await getter(config.handle)
        # Ensure chat is in database
        database.save_chat(chat_data)
        # Create directory
        os.makedirs(chat_data.directory, exist_ok=True)
        return chat_data

    @staticmethod
    async def load_messages(
            chat_data: 'ChatData', config: 'ChatConfig', client: TelegramClient, database: 'Database'
    ) -> List[Message]:
        logging.info(f"Initialising channel: {config}")
        # Get messages from database and channel, ensure they match
        database_messages = database.list_messages_for_chat(chat_data)
        channel_messages = [m async for m in client.iter_channel_messages(chat_data)]
        new_messages = set(channel_messages) - set(database_messages)
        removed_messages = set(database_messages) - set(channel_messages)
        for message_data in new_messages:
            database.save_message(message_data)
        for message_data in removed_messages:
            database.remove_message(message_data)
        # Check files, turn message data into messages
        messages = []
        for message in channel_messages:
            new_message = await Message.from_message_data(message, chat_data, client)
            messages.append(new_message)
            database.save_message(new_message.message_data)
        # Check for extra files which need removing
        dir_files = os.listdir(chat_data.directory)
        msg_files = [msg.message_data.file_path for msg in messages]
        excess_files = set(dir_files) - set(msg_files)
        for file in excess_files:
            try:
                os.unlink(file)
            except OSError:
                pass
        # Return group
        return messages

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.chat_data.title})"

    def remove_message(self, message_data: MessageData) -> None:
        self.messages = [msg for msg in self.messages if msg.message_data != message_data]

    @classmethod
    @abstractmethod
    async def from_config(cls, config: 'ChatConfig', client: TelegramClient, database: 'Database'):
        pass

    def message_by_id(self, message_id: int) -> Optional[Message]:
        return next(iter([msg for msg in self.messages if msg.message_data.message_id == message_id]), None)

    def add_message(self, message: Message) -> None:
        self.messages.append(message)


class Channel(Group):

    @classmethod
    async def from_config(cls, config: 'ChatConfig', client: TelegramClient, database: 'Database') -> Channel:
        chat_data = await Group.load_chat_data(client.get_channel_data, config, client, database)
        messages = await Group.load_messages(chat_data, config, client, database)
        return Channel(chat_data, config.queue, messages, client)


class WorkshopGroup(Group):

    @classmethod
    async def from_config(cls, config: 'ChatConfig', client: TelegramClient, database: 'Database') -> WorkshopGroup:
        chat_data = await Group.load_chat_data(client.get_workshop_data, config, client, database)
        messages = await Group.load_messages(chat_data, config, client, database)
        return WorkshopGroup(chat_data, config.queue, messages, client)
