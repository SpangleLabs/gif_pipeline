from __future__ import annotations

import logging
import os
import shutil
from abc import ABC, abstractmethod
from typing import Dict, Union, Any, TypeVar, List
from typing import TYPE_CHECKING

from message import Message, MessageData
from telegram_client import TelegramClient

if TYPE_CHECKING:
    from database import Database
T = TypeVar('T', bound='Group')


class ChatConfig(ABC):
    def __init__(self, handle: Union[str, int], queue: bool = False):
        self.handle = handle
        self.queue = queue

    @abstractmethod
    async def initialise(self, client: TelegramClient, database: 'Database') -> 'Group':
        pass

    async def init_group(self, group: T, client: TelegramClient, database: 'Database') -> T:
        logging.info(f"Initialising channel: {self}")
        # Get chat id, name, etc
        chat_entity = await client.get_entity(self.handle)
        # Ensure chat is in database
        database.upsert_chat(chat_entity.id, chat_entity.username, chat_entity.title)
        # Get messages from database and channel, ensure they match
        database_messages = database.list_messages_for_chat(chat_entity.id)
        channel_messages = await group.read_messages_from_channel(client)
        new_messages = set(channel_messages) - set(database_messages)
        removed_messages = set(database_messages) - set(channel_messages)
        for message_data in new_messages:
            database.save_message(message_data)
        for message_data in removed_messages:
            database.remove_message(message_data)
        # Check files, turn message data into messages
        group.create_directory()
        # TODO
        return group

    async def old_init(self):
        # TODO: remove
        # Create chat class
        directory_messages = group.read_messages_from_directory()
        channel_messages = await group.read_messages_from_channel(client)
        new_messages = [msg_id for msg_id in channel_messages.keys() if msg_id not in directory_messages]
        removed_messages = [msg_id for msg_id in directory_messages.keys() if msg_id not in channel_messages]
        logging.info(f"Channel: {self} has {len(new_messages)} new and {len(removed_messages)} removed messages")
        # Create a result dictionary from directory messages, with new channel messages, without removed messages
        for msg_id in new_messages:
            # Initialise all the new messages in channel, which may mean downloading videos
            # Doing this in serial to prevent requesting hundreds of files at once
            await channel_messages[msg_id].initialise_directory(client)
            directory_messages[msg_id] = channel_messages[msg_id]
        for msg_id in removed_messages:
            directory_messages[msg_id].delete_directory()
            directory_messages.pop(msg_id, None)
        # If we used channel messages, videos won't be set for non-new messages
        group.messages = directory_messages

    def read_file_message_ids_from_directory(self) -> List[int]:
        files = os.listdir(self.directory)
        # TODO
        return []

    def read_messages_from_directory(self) -> Dict[int, 'Message']:
        # TODO: remove me
        messages = {}
        # List subdirectories in directory and populate messages list
        subdirectories = [
            f"{self.directory}{message_dir}"
            for message_dir
            in os.listdir(self.directory)
            if os.path.isdir(f"{self.directory}{message_dir}")
        ]
        for subdirectory in subdirectories:
            try:
                message = Message.from_directory(self, subdirectory)
                if message is not None:
                    messages[message.message_id] = message
            except Exception as e:
                logging.warning(
                    f"Failed to read message from directory: {subdirectory}. Deleting directory. Exception: ",
                    exc_info=e
                )
                shutil.rmtree(subdirectory)
        return messages

    async def read_messages_from_channel(self, client: TelegramClient) -> List[MessageData]:
        return [m async for m in client.iter_channel_messages(self.handle)]

    @staticmethod
    @abstractmethod
    def from_json(json_dict: Dict[str, Any]) -> 'ChatConfig':
        pass


class ChannelConfig(ChatConfig):
    async def initialise(self, client: TelegramClient, database: 'Database') -> 'Channel':
        channel = Channel(self.handle, self.queue)
        return await self.init_group(channel, client, database)

    @staticmethod
    def from_json(json_dict) -> 'ChannelConfig':
        return ChannelConfig(json_dict['handle'], json_dict['queue'])


class WorkshopConfig(ChatConfig):
    async def initialise(self, client: TelegramClient, database: 'Database') -> 'WorkshopGroup':
        workshop = WorkshopGroup(self.handle)
        return await self.init_group(workshop, client, database)

    @staticmethod
    def from_json(json_dict) -> 'WorkshopConfig':
        return WorkshopConfig(json_dict['handle'])


class Group(ABC):
    def __init__(self, handle: Union[str, int], queue: bool = False):
        self.handle = handle
        self.queue = queue
        self.messages = {}  # type: Dict[int, Message]
        self.chat_id = None  # Optional[int]

    @property
    @abstractmethod
    def directory(self) -> str:
        pass

    def telegram_link_for_message(self, message: 'Message') -> str:
        handle = self.handle
        if isinstance(self.handle, int):
            handle = abs(self.handle)
        return f"https://t.me/c/{handle}/{message.message_id}"

    def create_directory(self):
        os.makedirs(self.directory, exist_ok=True)

    def __repr__(self):
        return f"{self.__class__.__name__}({self.handle})"


class Channel(Group):

    def __init__(self, handle: str, queue: bool = False):
        super().__init__(handle, queue)

    @property
    def directory(self) -> str:
        return f"store/channels/{self.handle}/"

    def telegram_link_for_message(self, message: 'Message') -> str:
        return f"https://t.me/{self.handle}/{message.message_id}"


class WorkshopGroup(Group):

    def __init__(self, handle: str):
        super().__init__(handle)

    @property
    def directory(self) -> str:
        return f"store/workshop/{self.handle}/"
