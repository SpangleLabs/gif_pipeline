import asyncio
import os
import re
from dataclasses import dataclass
from typing import Optional, List, ClassVar

import requests

from database import Database
from group import Group
from helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from message import Message
from tasks.ffmpeg_task import FfmpegTask
from tasks.ffmprobe_task import FFprobeTask
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient


@dataclass
class GifSettings:
    width: int
    height: int
    bitrate: int
    DEFAULT_WIDTH: ClassVar[int] = 1280
    DEFAULT_HEIGHT: ClassVar[int] = 1280
    DEFAULT_BITRATE: ClassVar[Optional[int]] = None

    @classmethod
    def from_input(cls, args: List[str]) -> "GifSettings":
        width, height = cls.DEFAULT_WIDTH, cls.DEFAULT_HEIGHT
        bitrate = cls.DEFAULT_BITRATE
        for arg in args:
            if len(arg.split("x")) == 2:
                width, height = [int(x) for x in arg.split("x")]
            else:
                try:
                    bitrate = int(arg)
                except ValueError:
                    if arg.lower().endswith("mbps"):
                        bitrate = 1_000_000 * int(arg[:-4])
                    elif arg.lower().endswith("kbps"):
                        bitrate = 1_000 * int(arg[:-4])
                    elif arg.lower().endswith("bps"):
                        bitrate = int(arg[:-3])
        return GifSettings(
            width=width,
            height=height,
            bitrate=bitrate
        )


class TelegramGifHelper(Helper):
    # Maximum gif dimension on android telegram is 1280px (width, or height, or both)
    # Maximum gif dimension on desktop telegram is 1440px (width, or height, or both)
    # On iOS, there is no maximum gif dimension. Even 5000px gifs display fine
    DEFAULT_WIDTH = 1280
    DEFAULT_HEIGHT = 1280
    FFMPEG_OPTIONS = " -an -vcodec libx264 -tune animation -preset veryslow -movflags faststart -pix_fmt yuv420p " \
                     "-vf \"scale='min({0},iw)':'min({1},ih)':force_original_aspect_" \
                     "ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2\" -profile:v baseline -level 3.0 -vsync vfr"
    # A handy read on Constant Rate Factor, and such https://trac.ffmpeg.org/wiki/Encode/H.264
    CRF_OPTION = " -crf 18"
    TARGET_SIZE_MB = 8

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        # If message has text which is a link to a gif, download it, then convert it
        gif_links = re.findall(r"[^\s]+\.gif", message.text, re.IGNORECASE)
        if gif_links:
            async with self.progress_message(chat, message, "Processing gif links in message"):
                return await asyncio.gather(*(self.convert_gif_link(chat, message, gif_link) for gif_link in gif_links))
        # If a message has text saying gif, and is a reply to a video, convert that video
        clean_text = message.text.strip().lower()
        if clean_text.startswith("gif"):
            args = clean_text[3:].strip().split()
            gif_settings = GifSettings.from_input(args)
            video = find_video_for_message(chat, message)
            if video is not None:
                async with self.progress_message(chat, message, "Converting video to telegram gif"):
                    new_path = await self.convert_video_to_telegram_gif(video.message_data.file_path, gif_settings)
                    video_reply = await self.send_video_reply(chat, message, new_path)
                return [video_reply]
            reply = await self.send_text_reply(
                chat,
                message,
                "Cannot work out which video you want to convert to a gif. "
                "Please reply to the video you want to convert with the message \"gif\"."
            )
            return [reply]
        # Otherwise, ignore
        return

    async def convert_gif_link(self, chat: Group, message: Message, gif_link: str) -> Message:
        resp = requests.get(gif_link)
        gif_path = random_sandbox_video_path("gif")
        with open(gif_path, "wb") as f:
            f.write(resp.content)
        new_path = await self.convert_video_to_telegram_gif(gif_path)
        return await self.send_video_reply(chat, message, new_path)

    async def convert_video_to_telegram_gif(
            self, video_path: str, gif_settings: GifSettings = None
    ) -> str:
        first_pass_filename = random_sandbox_video_path()
        gif_settings = gif_settings or GifSettings.from_input([])
        bitrate_option = f" -b:v {gif_settings.bitrate}" if gif_settings.bitrate else ""
        # first attempt
        ffmpeg_args = TelegramGifHelper.FFMPEG_OPTIONS.format(
            gif_settings.width, gif_settings.height
        ) + TelegramGifHelper.CRF_OPTION + bitrate_option
        task = FfmpegTask(
            inputs={video_path: None},
            outputs={first_pass_filename: ffmpeg_args}
        )
        await self.worker.await_task(task)
        # Check file size
        if os.path.getsize(first_pass_filename) < TelegramGifHelper.TARGET_SIZE_MB * 1000_000:
            return first_pass_filename
        # If it's too big, do a 2 pass run
        two_pass_filename = random_sandbox_video_path()
        # Get video duration from ffprobe
        probe_task = FFprobeTask(
            global_options=["-v error"],
            inputs={first_pass_filename: "-show_entries format=duration -of default=noprint_wrappers=1:nokey=1"}
        )
        duration = float(await self.worker.await_task(probe_task))
        # 2 pass run
        bitrate = min(
            TelegramGifHelper.TARGET_SIZE_MB / duration * 1000000 * 8,
            gif_settings.bitrate
        )
        t1_args = TelegramGifHelper.FFMPEG_OPTIONS.format(
            gif_settings.width, gif_settings.height
        ) + f" -b:v {bitrate} -pass 1 -f mp4"
        task1 = FfmpegTask(
            global_options=["-y"],
            inputs={video_path: None},
            outputs={os.devnull: t1_args}
        )
        await self.worker.await_task(task1)
        t2_args = TelegramGifHelper.FFMPEG_OPTIONS.format(
            gif_settings.width, gif_settings.height
        ) + f" -b:v {bitrate} -pass 2"
        task2 = FfmpegTask(
            global_options=["-y"],
            inputs={video_path: None},
            outputs={two_pass_filename: t2_args}
        )
        await self.worker.await_task(task2)
        return two_pass_filename
