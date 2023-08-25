import datetime
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


class ThumbnailHelper(Helper):

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
        thumbnail_ts = 1
        for arg in args[:]:
            try:
                thumbnail_ts = float(arg)
                args.remove(arg)
                break
            except ValueError:
                pass
        # Parse dimensions
        width = 500
        height = 500
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
            datetime.datetime.now()
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
