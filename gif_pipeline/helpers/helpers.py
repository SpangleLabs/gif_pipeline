import asyncio
import json
import logging
import os
import shutil
import uuid
from abc import ABC, abstractmethod
from typing import Optional, List, Set, Callable, TypeVar, Awaitable

from async_generator import asynccontextmanager
from prometheus_client import Counter
from telethon import Button
from telethon.tl.types import DocumentAttributeAudio, DocumentAttributeVideo

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat
from gif_pipeline.menu_cache import SentMenu
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask
from gif_pipeline.tasks.ffmprobe_task import FFprobeTask
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


def random_sandbox_video_path(file_ext: str = "mp4") -> str:
    os.makedirs("sandbox", exist_ok=True)
    return f"sandbox/{uuid.uuid4()}.{file_ext}"


T = TypeVar("T")
S = TypeVar("S")


async def ordered_post_task(tasks: List[Awaitable[T]], after_task: Callable[[T], Awaitable[S]]) -> List[S]:
    async def wrap_awaitable(i, f):
        return i, await f

    completed_tasks = {}
    results = {}

    async def process_tasks():
        for j in range(len(tasks)):
            if j in results:
                continue
            if j not in completed_ids:
                break
            results[j] = await after_task(completed_tasks[j])

    wrapped_tasks = [wrap_awaitable(i, f) for i, f in enumerate(tasks)]
    for coro in asyncio.as_completed(wrapped_tasks):
        i, result = await coro
        completed_tasks[i] = result
        required_ids = set(range(i))
        completed_ids = set(completed_tasks.keys())
        if len(required_ids - completed_ids) > 0:
            continue
        await process_tasks()
    await process_tasks()
    return [result for _, result in sorted(list(results.items()))]


def cleanup_file(file_path: str) -> None:
    if file_path is None:
        return
    try:
        os.remove(file_path)
    except FileNotFoundError:
        pass


class Helper(ABC):
    VIDEO_EXTENSIONS = ["mp4", "mov", "mkv", "webm", "avi", "wmv", "ogg", "vob", "flv", "gifv", "mpeg"]
    AUDIO_EXTENSIONS = ["mp3", "wav", "ogg", "flac"]

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
            tags=tags,
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
            voice_note: bool = False,
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
            extra_attributes = []
            thumb = None
            if file_ext.lower() in self.VIDEO_EXTENSIONS:
                video_metadata = await self._gather_video_metadata_attribute(video_path)
                if video_metadata:
                    extra_attributes.append(video_metadata)
                thumb = await self._create_video_thumbnail(video_path)
            if file_ext.lower() in self.AUDIO_EXTENSIONS:
                duration = await self._get_duration(video_path)
                duration_int = 0
                if duration:
                    duration_int = int(duration)
                extra_attributes.append(
                    DocumentAttributeAudio(duration_int, voice_note, filename, "Gif Pipeline", None)
                )
            msg = await self.client.send_video_message(
                chat.chat_data,
                video_path,
                text,
                reply_to_msg_id=reply_id,
                buttons=buttons,
                filename=filename,
                document_attributes=extra_attributes,
                thumb=thumb,
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

    async def _gather_video_metadata_attribute(self, video_path: str) -> Optional[DocumentAttributeVideo]:
        try:
            metadata_task = FFprobeTask(
                global_options=["-of json -v error"],
                inputs={video_path: "-show_entries format=duration:stream=width,height,bit_rate,codec_type"}
            )
            metadata_str = await self.worker.await_task(metadata_task)
            metadata_json = json.loads(metadata_str)
            duration = float(metadata_json.get("format", {}).get("duration", "0"))
            video_streams = [
                stream for stream in metadata_json.get("streams", []) if stream.get("codec_type") == "video"
            ]
            width = 0
            height = 0
            if video_streams:
                width = video_streams[0].get("width", 0)
                height = video_streams[0].get("height", 0)
            return DocumentAttributeVideo(int(duration), width, height)
        except Exception:
            return None
    
    async def _get_duration(self, video_path: str) -> Optional[float]:
        try:
            probe_task = FFprobeTask(
                global_options=["-v error"],
                inputs={video_path: "-show_entries format=duration -of default=noprint_wrappers=1:nokey=1"}
            )
            return float(await self.worker.await_task(probe_task))
        except Exception:
            return None

    async def _create_video_thumbnail(self, video_path: str) -> Optional[str]:
        try:
            thumb_path = random_sandbox_video_path("png")
            thumb_task = FfmpegTask(
                inputs={
                    video_path: None,
                },
                outputs={
                    thumb_path: "-ss 00:00:01.000 -vframes 1"
                }
            )
            await self.worker.await_task(thumb_task)
            if os.path.isfile(thumb_path):
                return thumb_path
            return None
        except Exception:
            return None


class ArchiveHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        # If a message says to archive, move to archive channel
        pass
