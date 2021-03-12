from typing import Optional, List

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask


class StabiliseHelper(Helper):

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.lower().strip()
        if text_clean not in ["stabilise", "stabilize", "stab", "deshake", "unshake"]:
            return
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "I'm not sure which video you would like to stabilise.")]
        output_path = random_sandbox_video_path()
        async with self.progress_message(chat, message, "Stabilising video"):
            task = FfmpegTask(
                inputs={video.message_data.file_path: None},
                outputs={output_path: "-vf deshake"}
            )
            await self.worker.await_task(task)
            return [await self.send_video_reply(chat, message, output_path, video.tags(self.database))]
