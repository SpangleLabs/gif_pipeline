import os
import re
from typing import Optional

from database import Database
from group import Group
from helpers.helpers import Helper, random_sandbox_video_path, find_video_for_message
from message import Message
from tasks.ffmpeg_task import FfmpegTask
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient


class VideoCropHelper(Helper):
    LEFT = ["left", "l"]
    RIGHT = ["right", "r"]
    TOP = ["top", "t"]
    BOTTOM = ["bottom", "b"]
    WIDTH = ["width", "w"]
    HEIGHT = ["height", "h"]
    VALID_WORDS = LEFT + RIGHT + TOP + BOTTOM + WIDTH + HEIGHT

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        # If a message has text saying to crop, some percentages maybe?
        # And is a reply to a video, then crop it
        text_clean = message.text.lower().strip()
        if not text_clean.startswith("crop"):
            return
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "I'm not sure which video you would like to crop.")]
        crop_args = text_clean[len("crop"):].strip()
        if crop_args.lower() == "auto":
            crop_string = await self.detect_crop(video.message_data.file_path)
            return [await self.send_text_reply(chat, message, crop_string)]
        crop_string = self.parse_crop_input(crop_args)
        if crop_string is None:
            return [await self.send_text_reply(
                chat,
                message,
                "I don't understand this crop command. "
                "Please specify what percentage to cut off the left, right, top, bottom. "
                "Alternatively specify the desired percentage for the width and height. "
                "Use the format `crop left 20% right 20% top 10%`. "
                "If the video has black bars you wish to crop, just use `crop auto`"
            )]
        output_path = random_sandbox_video_path()
        async with self.progress_message(chat, message, "Cropping video"):
            task = FfmpegTask(
                inputs={video.message_data.file_path: None},
                outputs={output_path: f"-filter:v \"{crop_string}\" -c:a copy"}
            )
            await self.worker.await_task(task)
            return [await self.send_video_reply(chat, message, output_path)]

    async def detect_crop(self, video_path: str):
        task = FfmpegTask(
            inputs={video_path: None},
            outputs={os.devnull: "-vf cropdetect=24:16:0"}
        )
        output = await self.worker.await_task(task)
        return output

    def parse_crop_input(self, input_clean: str) -> Optional[str]:
        input_split = re.split(r"[\s:=]", input_clean)
        if len(input_split) % 2 != 0:
            return None
        left, right, top, bottom, width, height = None, None, None, None, None, None
        for i in range(len(input_split) // 2):
            a, b = input_split[2 * i], input_split[(2 * i) + 1]
            word, value = None, None
            if a in self.VALID_WORDS:
                try:
                    word = a
                    value = int(b.strip("%"))
                except ValueError:
                    return None
            if b in self.VALID_WORDS:
                try:
                    word = b
                    value = int(a.strip("%"))
                except ValueError:
                    return None
            if word in self.LEFT:
                if width is not None:
                    return None
                left = value
            if word in self.RIGHT:
                if width is not None:
                    return None
                right = value
            if word in self.TOP:
                if height is not None:
                    return None
                top = value
            if word in self.BOTTOM:
                if height is not None:
                    return None
                bottom = value
            if word in self.WIDTH:
                if left is not None or right is not None:
                    return None
                width = value
            if word in self.HEIGHT:
                if top is not None or bottom is not None:
                    return None
                height = value
        # Normalise numbers
        if width is None:
            left = left or 0
            right = right or 0
            width = 100 - left - right
        else:
            width = width or 100
            left = (100 - width) / 2
            right = left
        if height is None:
            top = top or 0
            bottom = bottom or 0
            height = 100 - (top or 0) - (bottom or 0)
        else:
            height = height or 100
            top = (100 - height) / 2
            bottom = top
        # Check maximums
        if min(left, right, top, bottom, width, height) < 0:
            return None
        if max(width, height) > 100:
            return None
        # Create crop string
        return f"crop=in_w*{width / 100:.2f}:in_h*{height / 100:.2f}:in_w*{left / 100:.2f}:in_h*{top / 100:.2f}"
