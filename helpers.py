import asyncio
import os
import re
import subprocess
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Optional
import uuid

import ffmpy3
import requests

from channel import Message, Video
from telegram_client import TelegramClient


def find_video_for_message(message: Message) -> Optional[Video]:
    # If given message has a video, return that
    if message.has_video:
        return message.video
    # If it's a reply, return the video in that message
    if message.is_reply:
        reply_to = message.reply_to_msg_id
        reply_to_msg = message.channel.messages[reply_to]
        return reply_to_msg.video
    # Otherwise, get the video from the message above it?
    messages_above = [k for k, v in message.channel.messages.items() if k < message.message_id and v.has_video]
    if messages_above:
        return message.channel.messages[max(messages_above)].video
    return None


def random_sandbox_video_path(file_ext: str = "mp4"):
    os.makedirs("sandbox", exist_ok=True)
    return f"sandbox/{uuid.uuid4()}.{file_ext}"


class Helper(ABC):

    def __init__(self, client: TelegramClient):
        self.client = client

    async def send_text_reply(self, message: Message, text: str) -> Message:
        msg = await self.client.send_text_message(message.chat_id, text, reply_to_msg_id=message.message_id)
        new_message = await Message.from_telegram_message(message.channel, msg)
        message.channel[new_message.message_id] = new_message
        await new_message.initialise_directory(self.client)
        return new_message

    async def send_video_reply(self, message: Message, video_path: str, text: str = None) -> Message:
        msg = await self.client.send_video_message(
            message.chat_id, video_path, text,
            reply_to_msg_id=message.message_id
        )
        new_message = await Message.from_telegram_message(message.channel, msg)
        message.channel[new_message.message_id] = new_message
        file_ext = video_path.split(".")[-1]
        new_path = f"{message.directory}/{Video.FILE_NAME}.{file_ext}"
        os.rename(video_path, new_path)
        await new_message.initialise_directory(self.client)
        return new_message

    @contextmanager
    def progress_message(self, message: Message, text: str = None):
        if text is None:
            text = f"In progress. {self.name} is working on this."
        msg = self.client.synchronise_async(self.send_text_reply(message, text))
        yield
        self.client.synchronise_async(self.client.delete_message(message.chat_id, msg.message_id))

    @abstractmethod
    async def on_new_message(self, message: Message):
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__


class DuplicateHelper(Helper):

    def __init__(self, client: TelegramClient):
        # Initialise, get all channels, get all videos, decompose all, add to the master hash
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If message has a video, decompose it if necessary, then check images against master hash
        pass


class TelegramGifHelper(Helper):
    FFMPEG_OPTIONS = " -an -vcodec libx264 -tune animation -preset veryslow -movflags faststart -pix_fmt yuv420p " \
                     "-vf \"scale='min(1280,iw)':'min(720,ih)':force_original_aspect_" \
                     "ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2\" -profile:v baseline -level 3.0 -vsync vfr"
    CRF_OPTION = " -crf 18"
    TARGET_SIZE_MB = 8

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If message has text which is a link to a gif, download it, then convert it
        gif_links = re.findall(r"[^\s]+\.gif", message.text, re.IGNORECASE)
        if gif_links:
            with self.progress_message(message, "Processing gif links in message"):
                await asyncio.gather(self.convert_gif_link(message, gif_link) for gif_link in gif_links)
                return
        # If a message has text saying gif, and is a reply to a video, convert that video
        if "gif" in message.text.lower():
            video = find_video_for_message(message)
            if video is not None:
                with self.progress_message(message, "Converting video to telegram gif"):
                    new_path = await self.convert_video_to_telegram_gif(video.path)
                    await self.send_video_reply(message, new_path)
                return
            await self.send_text_reply(
                message,
                "Cannot work out which video you want to convert to a gif. "
                "Please reply to the video you want to convert with the message \"gif\"."
            )
            return
        # Otherwise, ignore
        return

    async def convert_gif_link(self, message: Message, gif_link: str):
        resp = requests.get(gif_link)
        gif_path = random_sandbox_video_path("gif")
        with open(gif_path, "wb") as f:
            f.write(resp.content)
        new_path = await self.convert_video_to_telegram_gif(gif_path)
        await self.send_video_reply(message, new_path)

    @staticmethod
    async def convert_video_to_telegram_gif(video_path: str) -> str:
        first_pass_filename = random_sandbox_video_path()
        # first pass
        ff = ffmpy3.FFmpeg(
            inputs={video_path: None},
            outputs={first_pass_filename: TelegramGifHelper.FFMPEG_OPTIONS + TelegramGifHelper.CRF_OPTION}
        )
        await ff.run_async()
        await ff.wait()
        # Check file size
        if os.path.getsize(first_pass_filename) < TelegramGifHelper.TARGET_SIZE_MB * 1000_000:
            return first_pass_filename
        # If it's too big, do a 2 pass run
        two_pass_filename = random_sandbox_video_path()
        # Get video duration from ffprobe
        ffprobe = ffmpy3.FFprobe(
            global_options=["-v error"],
            inputs={first_pass_filename: "-show_entries format=duration -of default=noprint_wrappers=1:nokey=1"}
        )
        ffprobe_process = await ffprobe.run_async(stdout=subprocess.PIPE)
        ffprobe_out = await ffprobe_process.communicate()
        await ffprobe.wait()
        duration = float(ffprobe_out[0].decode('utf-8').strip())
        # 2 pass run
        bitrate = TelegramGifHelper.TARGET_SIZE_MB / duration * 1000000 * 8
        ff1 = ffmpy3.FFmpeg(
            global_options=["-y"],
            inputs={video_path: None},
            outputs={os.devnull: TelegramGifHelper.FFMPEG_OPTIONS + " -b:v " + str(bitrate) + " -pass 1 -f mp4"}
        )
        await ff1.run_async()
        await ff1.wait()
        ff2 = ffmpy3.FFmpeg(
            global_options=["-y"],
            inputs={video_path: None},
            outputs={two_pass_filename: TelegramGifHelper.FFMPEG_OPTIONS + " -b:v " + str(bitrate) + " -pass 2"}
        )
        await ff2.run_async()
        await ff2.wait()
        return two_pass_filename


class TwitterDownloadHelper(Helper):

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message has a twitter link, and the twitter link has a video, download it
        pass


class YoutubeDownloadHelper(Helper):

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message has a youtube link, download it
        pass


class RedditDownloadHelper(Helper):

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message has text with a reddit link, and the reddit post has a video, download it
        pass


class GfycatDownloadHelper(Helper):

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message has text with a gfycat link, download it
        pass


class VideoCutHelper(Helper):

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message has text saying to cut, with times?
        # Maybe `cut start:end`, or `cut out start:end` and is a reply to a video, then cut it
        pass


class VideoRotateHelper(Helper):

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message has text saying to rotate, and is a reply to a video, then cut it
        # `rotate left`, `rotate right`, `flip horizontal`?, `rotate 90`, `rotate 180`
        pass


class VideoCropHelper(Helper):
    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message has text saying to crop, some percentages maybe?
        # And is a reply to a video, then crop it
        pass


class GifSendHelper(Helper):

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message says to send to a channel, and replies to a gif, then forward to that channel
        # `send deergifs`, `send cowgifs->deergifs`
        # Needs to handle queueing too?
        pass


class ArchiveHelper(Helper):

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message says to archive, move to archive channel
        pass


class DeleteHelper(Helper):

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message says to delete, delete it and delete local files
        pass
