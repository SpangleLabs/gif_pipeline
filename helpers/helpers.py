import os
import shutil
import uuid
from abc import ABC, abstractmethod
from typing import Optional, List

from async_generator import asynccontextmanager
from telethon import Button

from database import Database
from group import Group
from message import Message
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient, message_data_from_telegram


def find_video_for_message(chat: Group, message: Message) -> Optional[Message]:
    # If given message has a video, return that
    if message.has_video:
        return message
    # If it's a reply, return the video in that message
    if message.message_data.reply_to is not None:
        reply_to = message.message_data.reply_to
        return chat.message_by_id(reply_to)
    return None


def random_sandbox_video_path(file_ext: str = "mp4"):
    os.makedirs("sandbox", exist_ok=True)
    return f"sandbox/{uuid.uuid4()}.{file_ext}"


class Helper(ABC):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        self.database = database
        self.client = client
        self.worker = worker

    async def send_text_reply(
            self,
            chat: Group,
            message: Message,
            text: str,
            *,
            buttons: Optional[List[List[Button]]] = None
    ) -> Message:
        return await self.send_message(
            chat,
            text=text,
            reply_to_msg=message,
            buttons=buttons
        )

    async def send_video_reply(self, chat: Group, message: Message, video_path: str, text: str = None) -> Message:
        return await self.send_message(
            chat,
            video_path=video_path,
            reply_to_msg=message,
            text=text
        )

    async def send_message(
            self,
            chat: Group,
            *,
            text: Optional[str] = None,
            video_path: Optional[str] = None,
            reply_to_msg: Optional[Message] = None,
            buttons: Optional[List[List[Button]]] = None
    ) -> Message:
        reply_id = None
        if reply_to_msg is not None:
            reply_id = reply_to_msg.message_data.message_id
        if video_path is None:
            msg = await self.client.send_text_message(
                chat.chat_data,
                text,
                reply_to_msg_id=reply_id,
                buttons=buttons
            )
        else:
            msg = await self.client.send_video_message(
                chat.chat_data,
                video_path,
                text,
                reply_to_msg_id=reply_id,
                buttons=buttons
            )
        message_data = message_data_from_telegram(msg)
        if video_path is not None:
            # Copy file
            new_path = message_data.expected_file_path(chat.chat_data)
            shutil.copyfile(video_path, new_path)
            message_data.file_path = new_path
        # Set up message object
        new_message = await Message.from_message_data(message_data, chat.chat_data, self.client)
        self.database.save_message(new_message.message_data)
        chat.add_message(new_message)
        return new_message

    @asynccontextmanager
    async def progress_message(self, chat: Group, message: Message, text: str = None):
        if text is None:
            text = f"In progress. {self.name} is working on this."
        text = f"⏳ {text}"
        msg = await self.send_text_reply(chat, message, text)
        try:
            yield
        except Exception as e:
            await self.send_text_reply(chat, message, f"Command failed. {self.name} tried but failed to process this.")
            raise e
        finally:
            await self.client.delete_message(msg.message_data)
            chat.remove_message(msg.message_data)
            msg.delete(self.database)

    @abstractmethod
    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        pass

    async def on_deleted_message(self, chat: Group, message: Message) -> None:
        pass

    async def on_callback_query(self, chat: Group, callback_query: bytes) -> Optional[List[Message]]:
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__


class ArchiveHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        # If a message says to archive, move to archive channel
        pass


class DeleteHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        # If a message says to delete, delete it and delete local files
        pass
