from __future__ import annotations

import logging
import os
from abc import ABC
from typing import TYPE_CHECKING, Awaitable
from typing import TypeVar, List, Optional, Coroutine, Callable

from gif_pipeline.chat_config import ChatConfig, ChannelConfig, WorkshopConfig
from gif_pipeline.chat_data import C, ChatData, ChannelData, WorkshopData
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.telegram_client import TelegramClient
    from gif_pipeline.database import Database
    from gif_pipeline.message import MessageData
T = TypeVar('T', bound='Group')


class Chat(ABC):
    def __init__(
            self,
            chat_data: ChatData,
            config: ChatConfig,
            messages: List[Message],
            client: TelegramClient
    ):
        self.chat_data = chat_data
        self.config = config
        self.messages = messages
        self.client = client

    @staticmethod
    async def create_chat_data(
            getter: Callable[[str], Coroutine[None, None, C]],
            config: 'ChatConfig',
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
    async def list_message_initialisers(
            chat_data: 'ChatData',
            config: 'ChatConfig',
            client: TelegramClient,
            database: 'Database',
    ) -> List[Awaitable[Message]]:
        logging.info(f"Initialising chat: {config}")
        # Ensure bot is in chat
        if not config.read_only:
            await client.invite_pipeline_bot_to_chat(chat_data)
        # Get messages from database and channel, ensure they match
        database_messages = database.list_messages_for_chat(chat_data)
        channel_messages = [m async for m in client.iter_channel_messages(chat_data, not config.read_only)]
        new_messages = set(channel_messages) - set(database_messages)
        removed_messages = set(database_messages) - set(channel_messages)
        for message_data in new_messages:
            database.save_message(message_data)
        for message_data in removed_messages:
            database.remove_message(message_data)

        # Check files, turn message data into message objects
        async def save_message(message):
            old_file_path = message.file_path
            new_message = await Message.from_message_data(message, chat_data, client)
            if old_file_path != new_message.message_data.file_path:
                database.save_message(new_message.message_data)
            return new_message

        return [save_message(message) for message in channel_messages]

    def cleanup_excess_files(self):
        # Check for extra files which need removing
        dir_files = os.listdir(self.chat_data.directory)
        msg_files = [msg.message_data.file_path for msg in self.messages]
        excess_files = set(dir_files) - set(msg_files)
        for file in excess_files:
            try:
                os.unlink(file)
            except OSError:
                pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.chat_data.title})"

    def remove_message(self, message_data: MessageData) -> None:
        self.messages = [msg for msg in self.messages if msg.message_data != message_data]

    def message_by_id(self, message_id: int) -> Optional[Message]:
        return next(iter([msg for msg in self.messages if msg.message_data.message_id == message_id]), None)

    def message_by_link(self, link: str) -> Optional[Message]:
        return next(iter([msg for msg in self.messages if msg.telegram_link == link]), None)

    def add_message(self, message: Message) -> None:
        self.messages.append(message)


class Channel(Chat):

    def __init__(self, chat_data: ChannelData, config: ChannelConfig, messages: List[Message], client: TelegramClient):
        super().__init__(chat_data, config, messages, client)


class WorkshopGroup(Chat):

    def __init__(
            self,
            chat_data: WorkshopData,
            config: WorkshopConfig,
            messages: List[Message],
            client: TelegramClient
    ):
        super().__init__(chat_data, config, messages, client)
