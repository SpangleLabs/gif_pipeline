from typing import List, Optional, TYPE_CHECKING

from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask

if TYPE_CHECKING:
    from gif_pipeline.chat import Chat
    from gif_pipeline.message import Message


class ReverseHelper(Helper):
    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        clean_text = message.text.strip().lower()
        if clean_text != "reverse":
            return None
        self.usage_counter.inc()
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "Please reply to the video you want to reverse")]
        output_path = random_sandbox_video_path()
        reverse_task = FfmpegTask(
            inputs={video.message_data.file_path: None}, outputs={output_path: "-vf reverse -af areverse"}
        )
        async with self.progress_message(chat, message, "Reversing video"):
            await self.worker.await_task(reverse_task)
            return [await self.send_video_reply(chat, message, output_path, video.tags(self.database))]
