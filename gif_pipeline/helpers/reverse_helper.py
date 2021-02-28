from typing import Optional, List

from gif_pipeline.group import Group
from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask


class ReverseHelper(Helper):
    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        clean_text = message.text.strip().lower()
        if clean_text != "reverse":
            return None
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "Please reply to the video you want to reverse")]
        output_path = random_sandbox_video_path()
        reverse_task = FfmpegTask(
            inputs={video.message_data.file_path: None},
            outputs={output_path: "-vf reverse -af areverse"}
        )
        await self.worker.await_task(reverse_task)
        return [await self.send_video_reply(chat, message, output_path)]
