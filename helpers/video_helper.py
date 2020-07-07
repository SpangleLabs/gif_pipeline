from typing import Optional, List

from group import Group
from helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from message import Message
from tasks.ffmpeg_task import FfmpegTask
from tasks.ffmprobe_task import FFprobeTask


class VideoHelper(Helper):

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.lower().strip()
        if text_clean != "video":
            return
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "I'm not sure which video you want to video.")]
        output_path = random_sandbox_video_path()
        async with self.progress_message(chat, message, "Converting video into video"):
            if not await self.video_has_audio_track(video):
                task = FfmpegTask(
                    global_options=["-f lavfi"],
                    inputs={
                        "aevalsrc=0": None,
                        video.message_data.file_path: None
                    },
                    outputs={output_path: "-qscale:v 0 -acodec aac -map 0:0 -map 1:0 -shortest"}
                )
            else:
                task = FfmpegTask(
                    inputs={video.message_data.file_path: None},
                    outputs={output_path: "-qscale 0"}
                )
            await self.worker.await_task(task)
            return [await self.send_video_reply(chat, message, output_path)]

    async def video_has_audio_track(self, video: Message):
        task = FFprobeTask(
            global_options=["-v error"],
            inputs={video.message_data.file_path: "-show_streams -select_streams a -loglevel error"}
        )
        return len(await self.worker.await_task(task))
