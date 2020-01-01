import asyncio
import glob
import json
import os
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Optional, List, Set, Tuple, Match
import uuid

import ffmpy3
import imagehash
import requests
from PIL import Image
from async_generator import asynccontextmanager
import shutil

from channel import Message, Video, Channel, WorkshopGroup
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
        message.channel.messages[new_message.message_id] = new_message
        await new_message.initialise_directory(self.client)
        return new_message

    async def send_video_reply(self, message: Message, video_path: str, text: str = None) -> Message:
        msg = await self.client.send_video_message(
            message.chat_id, video_path, text,
            reply_to_msg_id=message.message_id
        )
        new_message = await Message.from_telegram_message(message.channel, msg)
        message.channel.messages[new_message.message_id] = new_message
        file_ext = video_path.split(".")[-1]
        new_path = f"{message.directory}/{Video.FILE_NAME}.{file_ext}"
        os.rename(video_path, new_path)
        await new_message.initialise_directory(self.client)
        return new_message

    @asynccontextmanager
    async def progress_message(self, message: Message, text: str = None):
        if text is None:
            text = f"In progress. {self.name} is working on this."
        msg = await self.send_text_reply(message, text)
        yield
        await self.client.delete_message(message.chat_id, msg.message_id)

    @abstractmethod
    async def on_new_message(self, message: Message):
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__


class DuplicateHelper(Helper):
    DECOMPOSE_DIRECTORY = "video_decompose"
    DECOMPOSE_JSON = "video_hashes.json"

    def __init__(self, client: TelegramClient):
        # Initialise, get all channels, get all videos, decompose all, add to the master hash
        super().__init__(client)
        self.hashes = {}

    async def initialise_hashes(self, channels: List[Channel], workshops: List[WorkshopGroup]):
        await asyncio.wait([self.add_channel_hashes_to_store(channel) for channel in channels])
        for workshop in workshops:
            workshop_messages = list(workshop.messages.values())
            for message in workshop_messages:
                hashes = await self.get_message_hashes(message)
                await self.check_hash_in_store(hashes, message)

    async def add_channel_hashes_to_store(self, channel: Channel):
        for message in channel.messages.values():
            hashes = await self.get_message_hashes(message)
            for image_hash in hashes:
                self.add_hash_to_store(image_hash, message)

    @staticmethod
    async def get_message_hashes(message: Message) -> List[str]:
        message_decompose_path = f"{message.directory}/{DuplicateHelper.DECOMPOSE_DIRECTORY}"
        try:
            with open(f"{message.directory}/{DuplicateHelper.DECOMPOSE_JSON}", "r") as f:
                message_hashes = json.load(f)
            if os.path.exists(message_decompose_path):
                shutil.rmtree(message_decompose_path)
            return message_hashes
        except FileNotFoundError:
            if message.video is None:
                return []
            # Decompose video into images
            if not os.path.exists(message_decompose_path):
                os.mkdir(message_decompose_path)
                await DuplicateHelper.decompose_video(message.video.full_path, message_decompose_path)
            # Hash the images
            hashes = []
            for image_file in glob.glob(f"{message_decompose_path}/*.png"):
                image = Image.open(image_file)
                image_hash = str(imagehash.dhash(image))
                hashes.append(image_hash)
            # Delete the images
            shutil.rmtree(message_decompose_path)
            # Save hashes
            with open(f"{message.directory}/{DuplicateHelper.DECOMPOSE_JSON}", "w") as f:
                json.dump(hashes, f)
            # Return hashes
            return hashes

    def add_hash_to_store(self, image_hash: str, message: Message):
        if image_hash not in self.hashes:
            self.hashes[image_hash] = set()
        self.hashes[image_hash].add(message)

    async def check_hash_in_store(self, image_hashes: List[str], message: Message):
        found_match = set()
        for image_hash in image_hashes:
            if image_hash in self.hashes:
                found_match = found_match.union(self.hashes[image_hash])
        if len(found_match) > 0:
            await self.post_duplicate_warning(message, found_match)
        for image_hash in image_hashes:
            self.add_hash_to_store(image_hash, message)

    async def post_duplicate_warning(self, new_message: Message, potential_matches: Set[Message]):
        message_links = [message.telegram_link for message in potential_matches]
        warning_message = "This video might be a duplicate of:\n" + "\n".join(message_links)
        await self.send_text_reply(new_message, warning_message)

    @staticmethod
    def get_image_hashes(decompose_directory: str):
        hashes = []
        for image_file in glob.glob(f"{decompose_directory}/*.png"):
            image = Image.open(image_file)
            image_hash = str(imagehash.average_hash(image))
            hashes.append(image_hash)
        return hashes

    @staticmethod
    async def decompose_video(video_path: str, decompose_dir_path: str):
        ff = ffmpy3.FFmpeg(
            inputs={video_path: None},
            outputs={f"{decompose_dir_path}/out%d.png": "-vf fps=5 -vsync 0"}
        )
        await ff.run_async()
        await ff.wait()

    async def on_new_message(self, message: Message):
        # If message has a video, decompose it if necessary, then check images against master hash
        if isinstance(message.channel, Channel):
            hashes = await self.get_message_hashes(message)
            for image_hash in hashes:
                self.add_hash_to_store(image_hash, message)
            return
        async with self.progress_message(message, "Checking whether this video has been seen before"):
            hashes = await self.get_message_hashes(message)
            await self.check_hash_in_store(hashes, message)


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
            async with self.progress_message(message, "Processing gif links in message"):
                await asyncio.gather(*(self.convert_gif_link(message, gif_link) for gif_link in gif_links))
                return
        # If a message has text saying gif, and is a reply to a video, convert that video
        if "gif" in message.text.lower():
            video = find_video_for_message(message)
            if video is not None:
                async with self.progress_message(message, "Converting video to telegram gif"):
                    new_path = await self.convert_video_to_telegram_gif(video.full_path)
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
        text_clean = message.text.lower().strip()
        cut_out = False
        if text_clean.startswith("cut out"):
            start, end = VideoCutHelper.get_start_and_end(text_clean[len("cut out"):].strip())
            cut_out = True
        elif text_clean.startswith("cut"):
            start, end = VideoCutHelper.get_start_and_end(text_clean[len("cut"):].strip())
        else:
            return None
        video = find_video_for_message(message)
        if video is None:
            return "C"
        if start is None and end is None:
            return await self.send_text_reply(
                message,
                "Start and end was not understood for this cut. "
                "Please provide start and end in the format MM:SS or as a number of seconds, with a space between them."
            )
        if cut_out and (start is None or end is None):
            cut_out = False
            if start is None:
                start = end
                end = None
            else:
                end = start
                start = None
        if not cut_out:
            new_path = random_sandbox_video_path()
            out_string = (f"-ss {start}" if start is not None else "") + " " + (f"-to {end}" if end is not None else "")
            ff = ffmpy3.FFmpeg(
                inputs={video.full_path: None},
                outputs={new_path: out_string}
            )
            await ff.run_async()
            await ff.wait()
            return await self.send_video_reply(message, new_path)
        first_part_path = random_sandbox_video_path()
        second_part_path = random_sandbox_video_path()
        ff1 = ffmpy3.FFmpeg(
            inputs={video.full_path: None},
            outputs={first_part_path: f"-to {start}"}
        )
        ff2 = ffmpy3.FFmpeg(
            inputs={video.full_path: None},
            outputs={second_part_path: f"-ss {end}"}
        )
        await asyncio.gather(ff1.run_async(), ff2.run_async())
        await asyncio.gather(ff1.wait(), ff2.wait())
        inputs_file = random_sandbox_video_path("txt")
        with open(inputs_file, "w") as f:
            f.write(f"file '{first_part_path.split('/')[1]}'\nfile '{second_part_path.split('/')[1]}'")
        output_path = random_sandbox_video_path()
        ff_concat = ffmpy3.FFmpeg(
            inputs={inputs_file: "-safe 0 -f concat"},
            outputs={output_path: "-c copy"}
        )
        await ff_concat.run_async()
        await ff_concat.wait()
        await self.send_video_reply(message, output_path)

    @staticmethod
    def get_start_and_end(text_clean: str) -> Tuple[Optional[str], Optional[str]]:
        if len(text_clean.split()) == 2:
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
        return re.fullmatch(r"^((\d+:)?\d\d:\d\d(\.\d+)?)|(\d+(\.\d+)?)$", timestamp)


class VideoRotateHelper(Helper):
    ROTATE_CLOCK = ["right", "90", "clock", "clockwise", "90clock", "90clockwise"]
    ROTATE_ANTICLOCK = [
        "left", "270", "anticlock", "anticlockwise", "90anticlock", "90anticlockwise", "cclock", "counterclock",
        "counterclockwise", "90cclock", "90counterclock", "90counterclockwise"
    ]
    ROTATE_180 = [
        "180", "180clockwise", "180anticlockwise", "180clock", "180anticlock", "180cclock", "180counterclock",
        "180counterclockwise"
    ]
    FLIP_HORIZONTAL = ["horizontal", "leftright"]
    FLIP_VERTICAL = ["vertical", "topbottom"]

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message has text saying to rotate, and is a reply to a video, then cut it
        # `rotate left`, `rotate right`, `flip horizontal`?, `rotate 90`, `rotate 180`
        text_clean = message.text.strip().lower().replace("-", "")
        if text_clean.startswith("rotate"):
            transpose = self.get_rotate_direction(text_clean[len("rotate"):].strip())
        elif text_clean.startswith("flip"):
            transpose = self.get_flip_direction(text_clean[len("flip"):].strip())
        else:
            return
        video = find_video_for_message(message)
        if video is None:
            await self.send_text_reply(message, "Cannot work out which video you want to rotate/flip.")
        if transpose is None:
            return await self.send_text_reply(message, "I do not understand this rotate/flip command.")
        async with self.progress_message(message, "Rotating or flipping video.."):
            output_path = random_sandbox_video_path()
            ff = ffmpy3.FFmpeg(
                inputs={video.full_path: None},
                outputs={output_path: f"-vf \"{transpose}\""}
            )
            await ff.run_async()
            await ff.wait()
            await self.send_video_reply(message, output_path)

    @staticmethod
    def get_rotate_direction(text_clean: str) -> Optional[str]:
        text_clean = text_clean.replace(" ", "")
        if text_clean in VideoRotateHelper.ROTATE_CLOCK:
            return "transpose=clock"
        if text_clean in VideoRotateHelper.ROTATE_ANTICLOCK:
            return "transpose=cclock"
        if text_clean in VideoRotateHelper.ROTATE_180:
            return "transpose=clock,transpose=clock"
        return None

    @staticmethod
    def get_flip_direction(text_clean: str) -> Optional[str]:
        text_clean = text_clean.replace(" ", "")
        if text_clean in VideoRotateHelper.FLIP_HORIZONTAL:
            return "transpose=cclock_flip,transpose=clock"
        if text_clean in VideoRotateHelper.FLIP_VERTICAL:
            return "transpose=clock,transpose=cclock_flip"
        return None


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
