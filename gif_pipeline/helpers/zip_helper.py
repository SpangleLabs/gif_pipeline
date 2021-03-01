import asyncio
import mimetypes
import shutil
import zipfile
from typing import Optional, List

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import random_sandbox_video_path
from gif_pipeline.helpers.telegram_gif_helper import TelegramGifHelper
from gif_pipeline.message import Message, mime_type_is_video
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask


class ZipHelper(TelegramGifHelper):
    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        if message.message_data.has_file and message.message_data.file_path.endswith(".zip"):
            async with self.progress_message(chat, message, "Unzipping file"):
                results = await self.unzip(chat, message)
                if results:
                    return results
                return [await self.send_text_reply(chat, message, "This zip file contained no video files.")]

    async def unzip(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        video_paths = []
        with zipfile.ZipFile(message.message_data.file_path, "r") as zip_ref:
            for filename in zip_ref.namelist():
                mime_type, _ = mimetypes.guess_type(filename)
                if mime_type_is_video(mime_type):
                    file_ext = filename.split(".")[-1]
                    video_path = random_sandbox_video_path(file_ext)
                    with zip_ref.open(filename) as zf, open(video_path, "wb") as f:
                        shutil.copyfileobj(zf, f)
                    video_paths.append(video_path)
        # Convert to mp4s
        processed_paths = await asyncio.gather(*(self.convert_file(path) for path in video_paths))
        # Send them
        if processed_paths:
            return await asyncio.gather(*(self.send_video_reply(chat, message, path) for path in processed_paths))
        return None

    async def convert_file(self, video_path: str) -> str:
        if video_path.endswith(".gif"):
            return await self.convert_video_to_telegram_gif(video_path)
        else:
            processed_path = random_sandbox_video_path()
            task = FfmpegTask(
                inputs={video_path: None},
                outputs={processed_path: "-qscale 0"}
            )
            await self.worker.await_task(task)
            return processed_path
