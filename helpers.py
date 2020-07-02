import asyncio
import glob
import os
import re
import shutil
import uuid
from abc import ABC, abstractmethod
from typing import Optional, List, Set, Tuple, Match, TypeVar, Dict

import imagehash
import requests
import youtube_dl
from PIL import Image
from async_generator import asynccontextmanager
from scenedetect import StatsManager, SceneManager, VideoManager, ContentDetector, FrameTimecode

from database import Database
from group import Channel, WorkshopGroup, Group
from message import Message, MessageData
from tasks.ffmpeg_task import FfmpegTask
from tasks.ffmprobe_task import FFprobeTask
from tasks.task_worker import TaskWorker
from tasks.youtube_dl_task import YoutubeDLTask
from telegram_client import TelegramClient, message_data_from_telegram

T = TypeVar('T')


def find_video_for_message(chat: Group, message: Message) -> Optional[Message]:
    # If given message has a video, return that
    if message.has_video:
        return message
    # If it's a reply, return the video in that message
    if message.message_data.reply_to is not None:
        reply_to = message.message_data.reply_to
        return chat.message_by_id(reply_to)
    return None


def random_sandbox_video_path(file_ext: str = "mp4"):
    os.makedirs("sandbox", exist_ok=True)
    return f"sandbox/{uuid.uuid4()}.{file_ext}"


class Helper(ABC):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        self.database = database
        self.client = client
        self.worker = worker

    async def send_text_reply(self, chat: Group, message: Message, text: str) -> Message:
        msg = await self.client.send_text_message(
            chat.chat_data.chat_id,
            text,
            reply_to_msg_id=message.message_data.message_id
        )
        message_data = message_data_from_telegram(msg)
        new_message = await Message.from_message_data(message_data, message.chat_data, self.client)
        self.database.save_message(new_message.message_data)
        chat.add_message(new_message)
        return new_message

    async def send_video_reply(self, chat: Group, message: Message, video_path: str, text: str = None) -> Message:
        msg = await self.client.send_video_message(
            chat.chat_data.chat_id, video_path, text,
            reply_to_msg_id=message.message_data.message_id
        )
        message_data = message_data_from_telegram(msg)
        # Copy file
        new_path = message_data.expected_file_path(message.chat_data)
        os.rename(video_path, new_path)
        message_data.file_path = new_path
        # Create message object
        new_message = await Message.from_message_data(message_data, message.chat_data, self.client)
        # Save to database
        self.database.save_message(new_message.message_data)
        # Add to channel
        chat.add_message(new_message)
        return new_message

    @asynccontextmanager
    async def progress_message(self, chat: Group, message: Message, text: str = None):
        if text is None:
            text = f"In progress. {self.name} is working on this."
        text = f"⏳ {text}"
        msg = await self.send_text_reply(chat, message, text)
        try:
            yield
        except Exception as e:
            await self.send_text_reply(chat, message, f"Command failed. {self.name} tried but failed to process this.")
            raise e
        finally:
            await self.client.delete_message(msg.message_data)
            chat.remove_message(msg.message_data)
            msg.delete(self.database)

    @abstractmethod
    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        pass

    async def on_deleted_message(self, chat: Group, message: Message) -> None:
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__


class DuplicateHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        # Initialise, get all channels, get all videos, decompose all, add to the master hash
        super().__init__(database, client, worker)

    async def initialise_hashes(self, channels: List[Channel], workshops: List[WorkshopGroup]):
        await asyncio.wait([self.create_channel_hashes(channel) for channel in channels])
        for workshop in workshops:
            workshop_messages = list(workshop.messages)
            for message in workshop_messages:
                existing_hashes = self.get_message_hashes(message)
                if existing_hashes is not None:
                    continue
                new_hashes = await self.create_message_hashes(message)
                await self.check_hash_in_store(workshop, new_hashes, message)

    async def create_channel_hashes(self, channel: Channel):
        for message in list(channel.messages):
            await self.get_or_create_message_hashes(message)

    async def get_or_create_message_hashes(self, message: Message) -> List[str]:
        existing_hashes = self.get_message_hashes(message)
        if existing_hashes is not None:
            return existing_hashes
        return await self.create_message_hashes(message)

    def get_message_hashes(self, message: Message) -> Optional[List[str]]:
        hashes = self.database.get_hashes_for_message(message.message_data)
        if hashes:
            return hashes
        return None

    async def create_message_hashes(self, message: Message) -> List[str]:
        if not message.has_video:
            return []
        message_decompose_path = f"sandbox/decompose/{message.chat_data.chat_id}-{message.message_data.message_id}/"
        # Decompose video into images
        os.makedirs(message_decompose_path, exist_ok=True)
        await self.decompose_video(message.message_data.file_path, message_decompose_path)
        # Hash the images
        hashes = []
        for image_file in glob.glob(f"{message_decompose_path}/*.png"):
            image = Image.open(image_file)
            image_hash = str(imagehash.dhash(image))
            hashes.append(image_hash)
        # Delete the images
        shutil.rmtree(message_decompose_path)
        # Save hashes
        self.database.save_hashes(message.message_data, hashes)
        # Return hashes
        return hashes

    async def check_hash_in_store(self, chat: Group, image_hashes: List[str], message: Message) -> Optional[Message]:
        matching_messages = set(self.database.get_messages_for_hashes(image_hashes))
        # TODO: get family, and ignore those ones
        warning_msg = None
        if len(matching_messages) > 0:
            warning_msg = await self.post_duplicate_warning(chat, message, matching_messages)
        return warning_msg

    async def post_duplicate_warning(self, chat: Group, new_message: Message, potential_matches: Set[MessageData]):
        message_links = [chat.chat_data.telegram_link_for_message(message) for message in potential_matches]
        warning_message = "This video might be a duplicate of:\n" + "\n".join(message_links)
        await self.send_text_reply(chat, new_message, warning_message)

    @staticmethod
    def get_image_hashes(decompose_directory: str):
        hashes = []
        for image_file in glob.glob(f"{decompose_directory}/*.png"):
            image = Image.open(image_file)
            image_hash = str(imagehash.average_hash(image))
            hashes.append(image_hash)
        return hashes

    async def decompose_video(self, video_path: str, decompose_dir_path: str):
        task = FfmpegTask(
            inputs={video_path: None},
            outputs={f"{decompose_dir_path}/out%d.png": "-vf fps=5 -vsync 0"},
            global_options="-y"
        )
        await self.worker.await_task(task)

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        # If message has a video, decompose it if necessary, then check images against master hash
        if isinstance(chat, Channel):
            await self.get_or_create_message_hashes(message)
            return
        if message.message_data.file_path is None:
            return
        progress_text = "Checking whether this video has been seen before"
        async with self.progress_message(chat, message, progress_text):
            hashes = await self.get_or_create_message_hashes(message)
            warning_msg = await self.check_hash_in_store(chat, hashes, message)
        if warning_msg is not None:
            return [warning_msg]

    async def on_deleted_message(self, chat: Group, message: Message):
        self.database.remove_message_hashes(message.message_data)


class TelegramGifHelper(Helper):
    FFMPEG_OPTIONS = " -an -vcodec libx264 -tune animation -preset veryslow -movflags faststart -pix_fmt yuv420p " \
                     "-vf \"scale='min(1280,iw)':'min(720,ih)':force_original_aspect_" \
                     "ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2\" -profile:v baseline -level 3.0 -vsync vfr"
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
        if clean_text == "gif":
            video = find_video_for_message(chat, message)
            if video is not None:
                async with self.progress_message(chat, message, "Converting video to telegram gif"):
                    new_path = await self.convert_video_to_telegram_gif(video.message_data.file_path)
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

    async def convert_video_to_telegram_gif(self, video_path: str) -> str:
        first_pass_filename = random_sandbox_video_path()
        # first pass
        task = FfmpegTask(
            inputs={video_path: None},
            outputs={first_pass_filename: TelegramGifHelper.FFMPEG_OPTIONS + TelegramGifHelper.CRF_OPTION}
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
        bitrate = TelegramGifHelper.TARGET_SIZE_MB / duration * 1000000 * 8
        task1 = FfmpegTask(
            global_options=["-y"],
            inputs={video_path: None},
            outputs={os.devnull: TelegramGifHelper.FFMPEG_OPTIONS + " -b:v " + str(bitrate) + " -pass 1 -f mp4"}
        )
        await self.worker.await_task(task1)
        task2 = FfmpegTask(
            global_options=["-y"],
            inputs={video_path: None},
            outputs={two_pass_filename: TelegramGifHelper.FFMPEG_OPTIONS + " -b:v " + str(bitrate) + " -pass 2"}
        )
        await self.worker.await_task(task2)
        return two_pass_filename


class DownloadHelper(Helper):
    LINK_REGEX = r'('
    # Scheme (HTTP, HTTPS, FTP and SFTP):
    LINK_REGEX += r'(?:(https?|s?ftp):\/\/)?'
    # www:
    LINK_REGEX += r'(?:www\.)?'
    LINK_REGEX += r'('
    # Host and domain (including ccSLD):
    LINK_REGEX += r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+)'
    # TLD:
    LINK_REGEX += r'([A-Z]{2,6})'
    # IP Address:
    LINK_REGEX += r'|(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    LINK_REGEX += r')'
    # Port:
    LINK_REGEX += r'(?::(\d{1,5}))?'
    # Query path:
    LINK_REGEX += r'(?:(\/\S+)*)'
    LINK_REGEX += r')'

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        if not message.text:
            return
        # TODO: something not awful
        if "Could not download video from link" in message.text:
            return
        matches = re.findall(DownloadHelper.LINK_REGEX, message.text, re.IGNORECASE)
        # Remove gif links, TelegramGifHelper handles those
        links = [match[0] for match in matches if self.link_is_monitored(match[0])]
        if not links:
            return
        async with self.progress_message(chat, message, "Downloading linked videos"):
            replies = []
            for link in links:
                replies.append(await self.handle_link(chat, message, link))
            return replies

    @staticmethod
    def link_is_monitored(link: str) -> bool:
        exclude_list = ["e621.net", "imgur.com/a/", "imgur.com/gallery/"]
        return not link.endswith(".gif") and all(exclude not in link for exclude in exclude_list)

    async def handle_link(self, chat: Group, message: Message, link: str) -> Message:
        try:
            download_filename = await self.download_link(link)
            return await self.send_video_reply(chat, message, download_filename)
        except (youtube_dl.utils.DownloadError, IndexError):
            return await self.send_text_reply(chat, message, f"Could not download video from link: {link}")

    async def download_link(self, link: str) -> str:
        output_path = random_sandbox_video_path("")
        task = YoutubeDLTask(link, output_path)
        return await self.worker.await_task(task)


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

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        # If a message has text saying to rotate, and is a reply to a video, then cut it
        # `rotate left`, `rotate right`, `flip horizontal`?, `rotate 90`, `rotate 180`
        text_clean = message.text.strip().lower().replace("-", "")
        if text_clean.startswith("rotate"):
            transpose = self.get_rotate_direction(text_clean[len("rotate"):].strip())
        elif text_clean.startswith("flip"):
            transpose = self.get_flip_direction(text_clean[len("flip"):].strip())
        else:
            return
        video = find_video_for_message(chat, message)
        if video is None:
            await self.send_text_reply(chat, message, "Cannot work out which video you want to rotate/flip.")
        if transpose is None:
            return [await self.send_text_reply(chat, message, "I do not understand this rotate/flip command.")]
        async with self.progress_message(chat, message, "Rotating or flipping video.."):
            output_path = random_sandbox_video_path()
            task = FfmpegTask(
                inputs={video.message_data.file_path: None},
                outputs={output_path: f"-vf \"{transpose}\""}
            )
            await self.worker.await_task(task)
            return [await self.send_video_reply(chat, message, output_path)]

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
        crop_string = self.parse_crop_input(text_clean[len("crop"):].strip())
        if crop_string is None:
            return [await self.send_text_reply(
                chat,
                message,
                "I don't understand this crop command. "
                "Please specify what percentage to cut off the left, right, top, bottom. "
                "Alternatively specify the desired percentage for the width and height. "
                "Use the format `crop left 20% right 20% top 10%`."
            )]
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "I'm not sure which video you would like to crop.")]
        output_path = random_sandbox_video_path()
        async with self.progress_message(chat, message, "Cropping video"):
            task = FfmpegTask(
                inputs={video.message_data.file_path: None},
                outputs={output_path: f"-filter:v \"{crop_string}\" -c:a copy"}
            )
            await self.worker.await_task(task)
            return [await self.send_video_reply(chat, message, output_path)]

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


class StabiliseHelper(Helper):

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.lower().strip()
        if text_clean not in ["stabilise", "stabilize", "stab", "deshake", "unshake"]:
            return
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "I'm not sure which video you would like to stabilise.")]
        output_path = random_sandbox_video_path()
        async with self.progress_message(chat, message, "Stabilising video"):
            task = FfmpegTask(
                inputs={video.message_data.file_path: None},
                outputs={output_path: "-vf deshake"}
            )
            await self.worker.await_task(task)
            return [await self.send_video_reply(chat, message, output_path)]


class QualityVideoHelper(Helper):

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


class MSGHelper(TelegramGifHelper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        # If message has relevant link in it
        matching_links = re.findall(r"e621.net/posts/([0-9]+)", message.text, re.IGNORECASE)
        if not matching_links:
            return None
        async with self.progress_message(chat, message, "Processing MSG links in message"):
            return await asyncio.gather(*(self.handle_post_link(chat, message, post_id) for post_id in matching_links))

    async def handle_post_link(self, chat: Group, message: Message, post_id: str):
        api_link = f"https://e621.net/posts/{post_id}.json"
        api_resp = requests.get(api_link, headers={"User-Agent": "Gif pipeline (my username is dr-spangle)"})
        api_data = api_resp.json()
        file_ext = api_data["post"]["file"]["ext"]
        if file_ext not in ["gif", "webm"]:
            return await self.send_text_reply(chat, message, "That post doesn't seem to be a gif or webm.")
        file_url = api_data["post"]["file"]["url"]
        # Download file
        resp = requests.get(file_url)
        file_path = random_sandbox_video_path(file_ext)
        with open(file_path, "wb") as f:
            f.write(resp.content)
        # If gif, convert to telegram gif
        if file_ext == "gif":
            file_path = await self.convert_video_to_telegram_gif(file_path)
        return await self.send_video_reply(chat, message, file_path)


class ImgurGalleryHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker, imgur_client_id: str):
        super().__init__(database, client, worker)
        self.imgur_client_id = imgur_client_id

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        # If message has imgur gallery/album link in it
        matching_links = re.findall(r"imgur.com/(?:gallery|a)/([0-9a-z]+)", message.text, re.IGNORECASE)
        if not matching_links:
            return None
        async with self.progress_message(chat, message, "Processing imgur gallery links in message"):
            galleries = await asyncio.gather(*(
                self.handle_gallery_link(chat, message, gallery_id) for gallery_id in matching_links
            ))
            return [message for gallery in galleries for message in gallery]

    async def handle_gallery_link(self, chat: Group, message: Message, gallery_id: str) -> List[Message]:
        api_url = "https://api.imgur.com/3/album/{}".format(gallery_id)
        api_key = f"Client-ID {self.imgur_client_id}"
        api_resp = requests.get(api_url, headers={"Authorization": api_key})
        api_data = api_resp.json()
        images = [image for image in api_data["data"]["images"] if "mp4" in image]
        if len(images) == 0:
            return [await self.send_text_reply(chat, message, "That imgur gallery contains no videos.")]
        return await asyncio.gather(*(self.send_imgur_video(chat, message, image) for image in images))

    async def send_imgur_video(self, chat: Group, message: Message, image: Dict[str, str]) -> Message:
        file_url = image["mp4"]
        file_ext = file_url.split(".")[-1]
        resp = requests.get(file_url)
        file_path = random_sandbox_video_path(file_ext)
        with open(file_path, "wb") as f:
            f.write(resp.content)
        return await self.send_video_reply(chat, message, file_path)


class AutoSceneSplitHelper(VideoCutHelper):

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.strip().lower()
        key_word = "split scenes"
        if not text_clean.startswith(key_word):
            return None
        args = text_clean[len(key_word):].strip()
        if len(args) == 0:
            threshold = 30
        else:
            try:
                threshold = int(args)
            except ValueError:
                return [await self.send_text_reply(
                    chat,
                    message,
                    "I don't understand that threshold setting. Please specify an integer. e.g. 'split scenes 20'"
                )]
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(
                chat,
                message,
                "I am not sure which video you would like to split. Please reply to the video with your split command."
            )]
        async with self.progress_message(chat, message, "Calculating scene list"):
            loop = asyncio.get_event_loop()
            scene_list = await loop.run_in_executor(None, self.calculate_scene_list, video, threshold)
        if len(scene_list) == 1:
            return [await self.send_text_reply(chat, message, "This video contains only 1 scene.")]
        progress_text = f"Splitting video into {len(scene_list)} scenes"
        async with self.progress_message(chat, message, progress_text):
            return await self.split_scenes(chat, message, video, scene_list)

    @staticmethod
    def calculate_scene_list(video: Message, threshold: int = 30) -> List[Tuple[FrameTimecode, FrameTimecode]]:
        video_manager = VideoManager([video.message_data.file_path])
        stats_manager = StatsManager()
        scene_manager = SceneManager(stats_manager)
        scene_manager.add_detector(ContentDetector(threshold=threshold))
        try:
            video_manager.start()
            base_timecode = video_manager.get_base_timecode()
            scene_manager.detect_scenes(frame_source=video_manager)
            scene_list = scene_manager.get_scene_list(base_timecode)
            return scene_list
        finally:
            video_manager.release()

    async def split_scenes(
            self,
            chat: Group,
            message: Message,
            video: Message,
            scene_list: List[Tuple[FrameTimecode, FrameTimecode]]
    ) -> Optional[List[Message]]:
        cut_videos = await asyncio.gather(*[
            self.cut_video(
                video,
                start_time.get_timecode(),
                end_time.previous_frame().get_timecode()
            ) for (start_time, end_time) in scene_list
        ])
        video_replies = []
        for new_path in cut_videos:
            video_replies.append(await self.send_video_reply(chat, message, new_path))
        return video_replies


class GifSendHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        # If a message says to send to a channel, and replies to a gif, then forward to that channel
        # `send deergifs`, `send cowgifs->deergifs`
        # Needs to handle queueing too?
        pass


class ArchiveHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        # If a message says to archive, move to archive channel
        pass


class DeleteHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        # If a message says to delete, delete it and delete local files
        pass
