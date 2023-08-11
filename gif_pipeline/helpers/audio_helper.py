import os
from typing import Optional, List

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from gif_pipeline.helpers.telegram_gif_helper import GifSettings
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask
from gif_pipeline.tasks.ffmprobe_task import FFprobeTask


class AudioHelper(Helper):
    CMD_AUDIO = ["audio", "mp3"]
    CMD_VOICE = ["voice", "voice note"]

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.lower().strip()
        if text_clean not in self.CMD_VOICE + self.CMD_AUDIO:
            return
        self.usage_counter.inc()
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "I'm not sure which video you want to audio.")]
        # Convert video to audio
        voice_note = text_clean in self.CMD_VOICE
        output_path = random_sandbox_video_path("ogg" if voice_note else "mp3")
        async with self.progress_message(chat, message, "Converting video into audio"):
            tasks = video_to_audio(video.message_data.file_path, output_path)
            for task in tasks:
                await self.worker.await_task(task)
            return [await self.send_message(
                chat,
                reply_to_msg=message,
                video_path=output_path,
                tags=video.tags(self.database),
                voice_note=voice_note,
            )]


def video_to_audio(input_path: str, output_path: str) -> List[FfmpegTask]:
    return [FfmpegTask(
        inputs={input_path: None},
        outputs={output_path: "-q:a 0 -map a"}
    )]
