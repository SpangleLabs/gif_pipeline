import re
from typing import Optional, Tuple, Match

from gif_pipeline.database import Database
from gif_pipeline.group import Group
from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class VideoCutHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        # If a message has text saying to cut, with times?
        # Maybe `cut start:end`, or `cut out start:end` and is a reply to a video, then cut it
        text_clean = message.text.lower().strip()
        cut_out = False
        if text_clean.startswith("cut out"):
            start, end = VideoCutHelper.get_start_and_end(text_clean[len("cut out"):].strip())
            cut_out = True
        elif text_clean.startswith("cut"):
            start, end = VideoCutHelper.get_start_and_end(text_clean[len("cut"):].strip())
        else:
            return None
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(
                chat,
                message,
                "I am not sure which video you would like to cut. Please reply to the video with your cut command."
            )]
        if start is None and end is None:
            return [await self.send_text_reply(
                chat,
                message,
                "Start and end was not understood for this cut. "
                "Please provide start and end in the format MM:SS or as a number of seconds, with a space between them."
            )]
        if cut_out and (start is None or end is None):
            cut_out = False
            if start is None:
                start = end
                end = None
            else:
                end = start
                start = None
        if not cut_out:
            async with self.progress_message(chat, message, "Cutting video"):
                new_path = await self.cut_video(video, start, end)
                return [await self.send_video_reply(chat, message, new_path)]
        async with self.progress_message(chat, message, "Cutting out video section"):
            output_path = await self.cut_out_video(video, start, end)
            return [await self.send_video_reply(chat, message, output_path)]

    async def cut_video(self, video: Message, start: Optional[str], end: Optional[str]) -> str:
        new_path = random_sandbox_video_path()
        out_string = (f"-ss {start}" if start is not None else "") + " " + (f"-to {end}" if end is not None else "")
        task = FfmpegTask(
            inputs={video.message_data.file_path: None},
            outputs={new_path: out_string}
        )
        await self.worker.await_task(task)
        return new_path

    async def cut_out_video(self, video: Message, start: str, end: str) -> str:
        first_part_path = random_sandbox_video_path()
        second_part_path = random_sandbox_video_path()
        task1 = FfmpegTask(
            inputs={video.message_data.file_path: None},
            outputs={first_part_path: f"-to {start}"}
        )
        task2 = FfmpegTask(
            inputs={video.message_data.file_path: None},
            outputs={second_part_path: f"-ss {end}"}
        )
        await self.worker.await_tasks([task1, task2])
        inputs_file = random_sandbox_video_path("txt")
        with open(inputs_file, "w") as f:
            f.write(f"file '{first_part_path.split('/')[1]}'\nfile '{second_part_path.split('/')[1]}'")
        output_path = random_sandbox_video_path()
        task_concat = FfmpegTask(
            inputs={inputs_file: "-safe 0 -f concat"},
            outputs={output_path: "-c copy"}
        )
        await self.worker.await_task(task_concat)
        return output_path

    @staticmethod
    def get_start_and_end(text_clean: str) -> Tuple[Optional[str], Optional[str]]:
        if len(text_clean.replace("-", " ").split()) == 2:
            start = text_clean.split()[0]
            end = text_clean.split()[1]
        elif len(text_clean.split(":")) == 2:
            start = text_clean.split(":")[0]
            end = text_clean.split(":")[1]
        else:
            return None, None
        if start in ["start"]:
            start = None
            if not VideoCutHelper.is_valid_timestamp(end):
                return None, None
        if end in ["end"]:
            end = None
            if not VideoCutHelper.is_valid_timestamp(start):
                return None, None
        return start, end

    @staticmethod
    def is_valid_timestamp(timestamp: str) -> Optional[Match[str]]:
        return re.fullmatch(r"^(((\d+:)?\d)?\d:\d\d(\.\d+)?)|(\d+(\.\d+)?)$", timestamp)
