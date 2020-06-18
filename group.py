import logging
import os
import shutil
from abc import ABC, abstractmethod
from typing import Dict, Union

from message import Message
from telegram_client import TelegramClient


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

    async def initialise_channel(self, client: TelegramClient):
        logging.info(f"Initialising channel: {self}")
        self.create_directory()
        directory_messages = self.read_messages_from_directory()
        channel_messages = await self.read_messages_from_channel(client)
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
        self.messages = directory_messages

    def read_messages_from_directory(self) -> Dict[int, 'Message']:
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

    async def read_messages_from_channel(self, client: TelegramClient) -> Dict[int, 'Message']:
        new_messages = {}
        async for message_data in client.iter_channel_messages(self.handle):
            self.chat_id = message_data.chat_id
            message = await Message.from_telegram_message(self, message_data)
            new_messages[message.message_id] = message
        return new_messages

    def __repr__(self):
        return f"{self.__class__.__name__}({self.handle})"


class Channel(Group):

    def __init__(self, handle: str, queue: bool = False):
        super().__init__(handle, queue)

    @property
    def directory(self) -> str:
        return f"store/channels/{self.handle}/"

    @staticmethod
    def from_json(json_dict) -> 'Channel':
        return Channel(json_dict['handle'], json_dict['queue'])

    def telegram_link_for_message(self, message: 'Message') -> str:
        return f"https://t.me/{self.handle}/{message.message_id}"


class WorkshopGroup(Group):

    def __init__(self, handle: str):
        super().__init__(handle)

    @property
    def directory(self) -> str:
        return f"store/workshop/{self.handle}/"
