import asyncio
import datetime
import logging
import os
from typing import Optional, List, TYPE_CHECKING

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, random_sandbox_video_path
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask

if TYPE_CHECKING:
    from gif_pipeline.database import Database
    from gif_pipeline.pipeline import Pipeline
    from gif_pipeline.tasks.task_worker import TaskWorker
    from gif_pipeline.telegram_client import TelegramClient


logger = logging.getLogger(__name__)


class ThumbnailHelper(Helper):
    DEFAULT_TS = 1
    DEFAULT_WIDTH = 500
    DEFAULT_HEIGHT = 500

    def __init__(self, database: "Database", client: "TelegramClient", worker: "TaskWorker", pipeline: "Pipeline"):
        super().__init__(database, client, worker)
        self.pipeline = pipeline

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        # If a message has text saying ffprobe or stats, and is a reply to a video, get stats for that video
        clean_args = message.text.strip().lower().split()
        if not clean_args or clean_args[0] not in ["thumbnail", "thumb"]:
            return
        args = clean_args[1:]
        # Get video
        video = chat.message_by_id(message.message_data.reply_to)
        if video is None:
            link = next(iter(args), None)
            if link:
                video = self.pipeline.get_message_for_link(link)
                args = args[1:]
        if not video:
            return [await self.send_text_reply(
                chat,
                message,
                "Cannot work out which video you want to create a thumbnail for. "
                "Please send your command as a reply to the video, or provide a link as the first argument"
            )]
        # Parse thumbnail timestamp
        thumbnail_ts = self.DEFAULT_TS
        for arg in args[:]:
            try:
                thumbnail_ts = float(arg)
                args.remove(arg)
                break
            except ValueError:
                pass
        # Parse dimensions
        width = self.DEFAULT_WIDTH
        height = self.DEFAULT_HEIGHT
        for arg in args[:]:
            if arg.count("x") == 1:
                w_str, h_str = arg.split("x")
                try:
                    width = int(w_str)
                    height = int(h_str)
                    args.remove(arg)
                    break
                except ValueError:
                    pass
        # Create thumbnail
        thumb_path = await self.create_thumbnail(video.message_data.file_path, thumbnail_ts, width, height)
        # If thumb is not generated return error
        if not thumb_path:
            return [
                await self.send_text_reply(chat, message, "Could not create that thumbnail of that video")
            ]
        # Save thumbnail to database
        with open(thumb_path, "rb") as f:
            thumb_data = f.read()
        self.database.save_thumbnail(
            video.message_data,
            thumb_data,
            thumbnail_ts,
            datetime.datetime.now(datetime.timezone.utc)
        )
        # Send thumbnail
        return [await self.send_message(
            chat,
            reply_to_msg=message,
            video_path=thumb_path,
        )]

    async def create_thumbnail(self, video_path: str, thumbnail_ts: float, width: int, height: int) -> Optional[str]:
        resize_filter = f"-vf \"scale='min({width},iw)':'min({height},ih)':force_original_aspect_ratio=decrease\""
        try:
            thumb_path = random_sandbox_video_path("jpg")
            thumb_task = FfmpegTask(
                inputs={
                    video_path: None,
                },
                outputs={
                    thumb_path: f"-ss {thumbnail_ts} -vframes 1 {resize_filter}"
                }
            )
            await self.worker.await_task(thumb_task)
            if os.path.isfile(thumb_path):
                return thumb_path
            return None
        except Exception:
            return None

    async def create_and_save_thumbnail(self, msg: Message) -> None:
        video_path = msg.message_data.file_path
        thumb_path = await self.create_thumbnail(video_path, self.DEFAULT_TS, self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        if not thumb_path:
            thumb_path = await self.create_thumbnail(video_path, 0, self.DEFAULT_WIDTH, self.DEFAULT_HEIGHT)
        now = datetime.datetime.now(datetime.timezone.utc)
        if thumb_path:
            with open(thumb_path, "rb") as f:
                thumb_data = f.read()
            self.database.save_thumbnail(msg.message_data, thumb_data, self.DEFAULT_TS, now)

    async def init_post_startup(self) -> None:
        for channel in self.pipeline.channels:
            if channel.config.website_config.enabled:
                logger.info("Checking %s for video thumbnails", channel.chat_data.title)
                for msg in channel.video_messages():
                    thumb = self.database.get_thumbnail_data(msg.message_data)
                    if not thumb:
                        asyncio.get_event_loop().create_task(self.create_and_save_thumbnail(msg))
        logger.info("Completed thumbnail checks")
        await super().init_post_startup()
