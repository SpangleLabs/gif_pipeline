import os
from typing import Optional, List

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from gif_pipeline.helpers.telegram_gif_helper import GifSettings
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask
from gif_pipeline.tasks.ffmprobe_task import FFprobeTask


class VideoHelper(Helper):

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.lower().strip()
        if not text_clean.startswith("video"):
            return
        self.usage_counter.inc()
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "I'm not sure which video you want to video.")]
        # Parse arguments, if present
        args = text_clean[5:].strip().split()
        gif_settings = None
        if args:
            gif_settings = GifSettings.from_input(args)
            gif_settings.audio = True
        # Convert video
        output_path = random_sandbox_video_path()
        async with self.progress_message(chat, message, "Converting video into video"):
            if not await self.video_has_audio_track(video):
                task = add_audio_track_task(video.message_data.file_path, output_path)
                await self.worker.await_task(task)
            else:
                tasks = video_to_video(video.message_data.file_path, output_path, gif_settings)
                for task in tasks:
                    await self.worker.await_task(task)
            return [await self.send_video_reply(chat, message, output_path, video.tags(self.database))]

    async def video_has_audio_track(self, video: Message) -> bool:
        task = video_has_audio_track_task(video.message_data.file_path)
        return bool(len(await self.worker.await_task(task)))


def video_has_audio_track_task(input_path: str) -> FFprobeTask:
    return FFprobeTask(
        global_options=["-v error"],
        inputs={input_path: "-show_streams -select_streams a -loglevel error"}
    )


def add_audio_track_task(input_path: str, output_path: str) -> FfmpegTask:
    return FfmpegTask(
        global_options=["-f lavfi"],
        inputs={
            "aevalsrc=0": None,
            input_path: None
        },
        outputs={output_path: "-qscale:v 0 -acodec aac -map 0:0 -map 1:0 -shortest"}
    )


def video_to_video(
        input_path: str,
        output_path: str,
        video_settings: Optional[GifSettings] = None,
        task_description: Optional[str] = None
) -> List[FfmpegTask]:
    if not video_settings:
        return [FfmpegTask(
            inputs={input_path: None},
            outputs={output_path: "-qscale 0"},
            description=task_description,
        )]
    if video_settings.bitrate:
        tasks = two_pass_convert(input_path, output_path, video_settings)
    else:
        tasks = [single_pass_convert(input_path, output_path, video_settings)]
    return tasks


def single_pass_convert(input_path: str, output_path: str, video_settings: GifSettings) -> FfmpegTask:
    # first attempt
    ffmpeg_args = video_settings.ffmpeg_options_one_pass
    return FfmpegTask(
        inputs={input_path: None},
        outputs={output_path: ffmpeg_args}
    )


def two_pass_convert(input_path: str, output_path: str, video_settings: GifSettings) -> List[FfmpegTask]:
    two_pass_args = video_settings.ffmpeg_options_two_pass
    task1 = FfmpegTask(
        global_options=["-y"],
        inputs={input_path: None},
        outputs={os.devnull: two_pass_args[0]}
    )
    task2 = FfmpegTask(
        global_options=["-y"],
        inputs={input_path: None},
        outputs={output_path: two_pass_args[1]}
    )
    return [task1, task2]
