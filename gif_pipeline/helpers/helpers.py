import logging
import os
import shutil
import uuid
from abc import ABC, abstractmethod
from typing import Optional, List, Set

from async_generator import asynccontextmanager
from prometheus_client import Counter
from telethon import Button

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat
from gif_pipeline.menu_cache import SentMenu
from gif_pipeline.message import Message
from gif_pipeline.video_tags import VideoTags
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient, message_data_from_telegram

usage_counter = Counter(
    "gif_pipeline_helper_usage_total",
    "Total usage of gif pipeline helpers",
    labelnames=["class_name"]
)

logger = logging.getLogger(__name__)


def find_video_for_message(chat: Chat, message: Message) -> Optional[Message]:
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
        self.usage_counter = usage_counter.labels(class_name=self.__class__.__name__)

    async def send_text_reply(
            self,
            chat: Chat,
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

    async def send_video_reply(
            self,
            chat: Chat,
            message: Message,
            video_path: str,
            tags: VideoTags,
            text: str = None,
    ) -> Message:
        return await self.send_message(
            chat,
            video_path=video_path,
            reply_to_msg=message,
            text=text,
            tags=tags
        )

    async def send_message(
            self,
            chat: Chat,
            *,
            text: Optional[str] = None,
            video_path: Optional[str] = None,
            reply_to_msg: Optional[Message] = None,
            buttons: Optional[List[List[Button]]] = None,
            tags: Optional[VideoTags] = None,
            video_hashes: Optional[Set[str]] = None,
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
            # Set filename
            est_next_msg_id = 1
            if chat.latest_message():
                est_next_msg_id = chat.latest_message().message_data.message_id + 1
            file_ext = video_path.split(".")[-1]
            if chat.chat_data.username:
                filename = f"{chat.chat_data.username}_{est_next_msg_id}.{file_ext}"
            else:
                filename = f"gif_pipeline_{est_next_msg_id}.{file_ext}"
            msg = await self.client.send_video_message(
                chat.chat_data,
                video_path,
                text,
                reply_to_msg_id=reply_id,
                buttons=buttons,
                filename=filename
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
        if tags:
            self.database.save_tags(new_message.message_data, tags)
        if video_hashes:
            self.database.save_hashes(new_message.message_data, video_hashes)
        chat.add_message(new_message)
        return new_message

    async def edit_message(
            self,
            chat: Chat,
            message: Message,
            *,
            new_text: Optional[str] = None,
            new_buttons: Optional[List[List[Button]]] = None
    ) -> Message:
        msg = await self.client.edit_message(chat.chat_data, message.message_data, new_text, new_buttons)
        message_data = message_data_from_telegram(msg)
        new_message = await Message.from_message_data(message_data, chat.chat_data, self.client)
        chat.remove_message(message_data)
        chat.add_message(new_message)
        self.database.save_message(new_message.message_data)
        return new_message

    @asynccontextmanager
    async def progress_message(self, chat: Chat, message: Message, text: str = None):
        if text is None:
            text = f"In progress. {self.name} is working on this."
        text = f"⏳ {text}"
        msg = await self.send_text_reply(chat, message, text)
        try:
            yield
        except Exception as e:
            logger.error(
                "Helper %s failed to process message %s in chat %s",
                self.name,
                message.message_data.message_id,
                message.message_data.chat_id,
                exc_info=e
            )
            await self.send_text_reply(chat, message, f"Command failed. {self.name} tried but failed to process this.")
            raise e
        finally:
            await self.client.delete_message(msg.message_data)
            chat.remove_message(msg.message_data)
            msg.delete(self.database)

    @abstractmethod
    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        pass

    async def on_deleted_message(self, chat: Chat, message: Message) -> None:
        pass

    async def on_callback_query(
            self,
            callback_query: bytes,
            menu: SentMenu,
            sender_id: int,
    ) -> Optional[List[Message]]:
        pass

    async def on_stateless_callback(
            self,
            callback_query: bytes,
            chat: Chat,
            message: Message,
            sender_id: int,
    ) -> Optional[List[Message]]:
        pass

    def is_priority(self, chat: Chat, message: Message) -> bool:
        return False

    @property
    def name(self) -> str:
        return self.__class__.__name__


class ArchiveHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        # If a message says to archive, move to archive channel
        pass
