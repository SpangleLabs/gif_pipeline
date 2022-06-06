from __future__ import annotations
from typing import Optional, List

import isodate

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat
from gif_pipeline.helpers.ffprobe_helper import FFProbeHelper
from gif_pipeline.helpers.helpers import find_video_for_message, ordered_post_task
from gif_pipeline.helpers.video_cut_helper import VideoCutHelper
from gif_pipeline.message import Message
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class ChunkSplitHelper(VideoCutHelper):

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            ffprobe_helper: FFProbeHelper,
    ) -> None:
        super().__init__(database, client, worker)
        self.ffprobe_helper = ffprobe_helper

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.strip().lower()
        key_words = ["split chunks", "chunksplit", "chunk split", "chunks", "chunk"]
        args = None
        for key_word in key_words:
            if text_clean.startswith(key_word):
                args = text_clean[len(key_word):].strip()
                break
        if args is None:
            return None
        self.usage_counter.inc()
        if not args:
            return [await self.send_text_reply(
                chat,
                message,
                "Please specify a chunk length in seconds, or with a duration. e.g. 'split chunks 30'."
            )]
        try:
            chunk_length = float(args)
        except ValueError:
            try:
                chunk_length = isodate.parse_duration(args).total_seconds()
            except isodate.ISO8601Error:
                return [await self.send_text_reply(
                    chat,
                    message,
                    "This chunk length was not understood. "
                    "Please use a number to specify seconds, or an ISO8601 duration."
                )]
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(
                chat,
                message,
                "I am not sure which video you would like to split. Please reply to the video with your split command."
            )]
        async with self.progress_message(chat, message, "Cutting video into chunks"):
            video_path = video.message_data.file_path
            video_length = await self.ffprobe_helper.duration_video(video_path)
            chunk_count = int(video_length // chunk_length) + 1
            if chunk_count == 1:
                return [await self.send_text_reply(chat, message, "This video is shorter than that chunk length.")]
            timestamps = [
                (
                    i*chunk_length if i != 0 else None,
                    (i+1)*chunk_length if (i+1)*chunk_length <= video_length else None
                )
                for i in range(chunk_count)
            ]
            return await ordered_post_task(
                [self.cut_video(video, start, end) for start, end in timestamps],
                lambda path: self.send_video_reply(chat, message, path, video.tags(self.database))
            )
