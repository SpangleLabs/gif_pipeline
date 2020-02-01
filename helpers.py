import asyncio
import glob
import json
import os
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Optional, List, Set, Tuple, Match, Dict
import uuid

import ffmpy3
import imagehash
import requests
import youtube_dl
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
        # Set up history
        message.extend_history_from(reply_to_msg)
        return reply_to_msg.video
    # Otherwise, get the video from the message above it?
    messages_above = [k for k, v in message.channel.messages.items() if k < message.message_id and v.has_video]
    if messages_above:
        msg_above = message.channel.messages[max(messages_above)]
        # Set up history
        message.extend_history_from(msg_above)
        return msg_above.video
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
        new_message.extend_history_from(message)
        await new_message.initialise_directory(self.client)
        return new_message

    async def send_video_reply(self, message: Message, video_path: str, text: str = None) -> Message:
        msg = await self.client.send_video_message(
            message.chat_id, video_path, text,
            reply_to_msg_id=message.message_id
        )
        new_message = await Message.from_telegram_message(message.channel, msg)
        message.channel.messages[new_message.message_id] = new_message
        new_message.extend_history_from(message)
        file_ext = video_path.split(".")[-1]
        new_path = f"{new_message.directory}/{Video.FILE_NAME}.{file_ext}"
        os.makedirs(new_message.directory, exist_ok=True)
        os.rename(video_path, new_path)
        await new_message.initialise_directory(self.client)
        return new_message

    @asynccontextmanager
    async def progress_message(self, message: Message, text: str = None):
        if text is None:
            text = f"In progress. {self.name} is working on this."
        text = f"⏳ {text}"
        msg = await self.send_text_reply(message, text)
        try:
            yield
        except Exception as e:
            await self.send_text_reply(message, f"Command failed. {self.name} tried but failed to process this.")
            raise e
        finally:
            await self.client.delete_message(message.chat_id, msg.message_id)

    @abstractmethod
    async def on_new_message(self, message: Message) -> Optional[List[Message]]:
        pass

    async def on_deleted_message(self, message: Message):
        pass

    @property
    def name(self) -> str:
        return self.__class__.__name__


class DuplicateHelper(Helper):
    hashes: Dict[str, Set[Message]]
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
                existing_hashes = await self.get_message_hashes(message)
                if existing_hashes is not None:
                    for image_hash in existing_hashes:
                        self.add_hash_to_store(image_hash, message)
                    continue
                new_hashes = await self.create_message_hashes(message)
                await self.check_hash_in_store(new_hashes, message)

    async def add_channel_hashes_to_store(self, channel: Channel):
        for message in channel.messages.values():
            hashes = await self.get_or_create_message_hashes(message)
            for image_hash in hashes:
                self.add_hash_to_store(image_hash, message)

    @staticmethod
    async def get_message_hashes(message: Message) -> Optional[List[str]]:
        message_decompose_path = f"{message.directory}/{DuplicateHelper.DECOMPOSE_DIRECTORY}"
        try:
            with open(f"{message.directory}/{DuplicateHelper.DECOMPOSE_JSON}", "r") as f:
                message_hashes = json.load(f)
            if os.path.exists(message_decompose_path):
                shutil.rmtree(message_decompose_path)
            return message_hashes
        except FileNotFoundError:
            return None

    @staticmethod
    async def create_message_hashes(message: Message) -> List[str]:
        message_decompose_path = f"{message.directory}/{DuplicateHelper.DECOMPOSE_DIRECTORY}"
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

    @staticmethod
    async def get_or_create_message_hashes(message: Message) -> List[str]:
        existing_hashes = await DuplicateHelper.get_message_hashes(message)
        if existing_hashes is not None:
            return existing_hashes
        return await DuplicateHelper.create_message_hashes(message)

    def add_hash_to_store(self, image_hash: str, message: Message):
        if image_hash not in self.hashes:
            self.hashes[image_hash] = set()
        self.hashes[image_hash].add(message)

    def remove_hash_from_store(self, image_hash: str, message: Message):
        if image_hash not in self.hashes:
            return
        self.hashes[image_hash].discard(message)

    async def check_hash_in_store(self, image_hashes: List[str], message: Message) -> Optional[Message]:
        found_match = set()
        for image_hash in image_hashes:
            if image_hash in self.hashes:
                matches_not_in_history = {
                    msg
                    for msg in self.hashes[image_hash]
                    if msg.telegram_link not in message.history
                }
                found_match = found_match.union(matches_not_in_history)
        warning_msg = None
        if len(found_match) > 0:
            warning_msg = await self.post_duplicate_warning(message, found_match)
        for image_hash in image_hashes:
            self.add_hash_to_store(image_hash, message)
        return warning_msg

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

    async def on_new_message(self, message: Message) -> Optional[List[Message]]:
        # If message has a video, decompose it if necessary, then check images against master hash
        if isinstance(message.channel, Channel):
            hashes = await self.get_or_create_message_hashes(message)
            for image_hash in hashes:
                self.add_hash_to_store(image_hash, message)
            return
        if message.video is None:
            return
        async with self.progress_message(message, "Checking whether this video has been seen before"):
            hashes = await self.get_or_create_message_hashes(message)
            warning_msg = await self.check_hash_in_store(hashes, message)
        if warning_msg is not None:
            return [warning_msg]

    async def on_deleted_message(self, message: Message):
        hashes = await self.get_or_create_message_hashes(message)
        for image_hash in hashes:
            self.remove_hash_from_store(image_hash, message)


# noinspection PyUnresolvedReferences
class TelegramGifHelper(Helper):
    FFMPEG_OPTIONS = " -an -vcodec libx264 -tune animation -preset veryslow -movflags faststart -pix_fmt yuv420p " \
                     "-vf \"scale='min(1280,iw)':'min(720,ih)':force_original_aspect_" \
                     "ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2\" -profile:v baseline -level 3.0 -vsync vfr"
    CRF_OPTION = " -crf 18"
    TARGET_SIZE_MB = 8

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message) -> Optional[List[Message]]:
        # If message has text which is a link to a gif, download it, then convert it
        gif_links = re.findall(r"[^\s]+\.gif", message.text, re.IGNORECASE)
        if gif_links:
            async with self.progress_message(message, "Processing gif links in message"):
                return await asyncio.gather(*(self.convert_gif_link(message, gif_link) for gif_link in gif_links))
        # If a message has text saying gif, and is a reply to a video, convert that video
        if re.search(r"\bgif\b", message.text, re.IGNORECASE):
            video = find_video_for_message(message)
            if video is not None:
                async with self.progress_message(message, "Converting video to telegram gif"):
                    new_path = await self.convert_video_to_telegram_gif(video.full_path)
                    video_reply = await self.send_video_reply(message, new_path)
                return [video_reply]
            reply = await self.send_text_reply(
                message,
                "Cannot work out which video you want to convert to a gif. "
                "Please reply to the video you want to convert with the message \"gif\"."
            )
            return [reply]
        # Otherwise, ignore
        return

    async def convert_gif_link(self, message: Message, gif_link: str) -> Message:
        resp = requests.get(gif_link)
        gif_path = random_sandbox_video_path("gif")
        with open(gif_path, "wb") as f:
            f.write(resp.content)
        new_path = await self.convert_video_to_telegram_gif(gif_path)
        return await self.send_video_reply(message, new_path)

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

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        if not message.text:
            return
        # TODO: something not awful
        if "Could not download video from link" in message.text:
            return
        matches = re.findall(DownloadHelper.LINK_REGEX, message.text, re.IGNORECASE)
        # Remove gif links, TelegramGifHelper handles those
        links = [match[0] for match in matches if not match[0].endswith(".gif")]
        if not links:
            return
        async with self.progress_message(message, "Downloading linked videos"):
            replies = []
            for link in links:
                replies.append(await self.handle_link(message, link))
            return replies

    async def handle_link(self, message: Message, link: str) -> Message:
        try:
            download_filename = self.download_link(link)
            return await self.send_video_reply(message, download_filename)
        except (youtube_dl.utils.DownloadError, IndexError):
            return await self.send_text_reply(
                message, f"Could not download video from link: {link}"
            )

    @staticmethod
    def download_link(link: str) -> str:
        output_path = random_sandbox_video_path("")
        ydl_opts = {"outtmpl": f"{output_path}%(ext)s"}
        # If downloading from reddit, use the DASH video, not the HLS video, which has corruption at 6 second intervals
        if "v.redd.it" in link or "reddit.com" in link:
            ydl_opts["format"] = "dash-VIDEO-1+dash-AUDIO-1/bestvideo+bestaudio/best"
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([link])
        files = glob.glob(f"{output_path}*")
        return files[0]


# noinspection PyUnresolvedReferences
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
            return [await self.send_text_reply(
                message,
                "I am not sure which video you would like to cut. Please reply to the video with your cut command."
            )]
        if start is None and end is None:
            return [await self.send_text_reply(
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
            async with self.progress_message(message, "Cutting video"):
                new_path = await VideoCutHelper.cut_video(video, start, end)
                return [await self.send_video_reply(message, new_path)]
        async with self.progress_message(message, "Cutting out video section"):
            output_path = await VideoCutHelper.cut_out_video(video, start, end)
            return [await self.send_video_reply(message, output_path)]

    @staticmethod
    async def cut_video(video: Video, start: Optional[str], end: Optional[str]) -> str:
        new_path = random_sandbox_video_path()
        out_string = (f"-ss {start}" if start is not None else "") + " " + (f"-to {end}" if end is not None else "")
        ff = ffmpy3.FFmpeg(
            inputs={video.full_path: None},
            outputs={new_path: out_string}
        )
        await ff.run_async()
        await ff.wait()
        return new_path

    @staticmethod
    async def cut_out_video(video: Video, start: str, end: str) -> str:
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
        return re.fullmatch(r"^((\d+:)?\d\d:\d\d(\.\d+)?)|(\d+(\.\d+)?)$", timestamp)


# noinspection PyUnresolvedReferences
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
            return [await self.send_text_reply(message, "I do not understand this rotate/flip command.")]
        async with self.progress_message(message, "Rotating or flipping video.."):
            output_path = random_sandbox_video_path()
            ff = ffmpy3.FFmpeg(
                inputs={video.full_path: None},
                outputs={output_path: f"-vf \"{transpose}\""}
            )
            await ff.run_async()
            await ff.wait()
            return [await self.send_video_reply(message, output_path)]

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


# noinspection PyUnresolvedReferences
class VideoCropHelper(Helper):
    LEFT = ["left", "l"]
    RIGHT = ["right", "r"]
    TOP = ["top", "t"]
    BOTTOM = ["bottom", "b"]
    WIDTH = ["width", "w"]
    HEIGHT = ["height", "h"]
    VALID_WORDS = LEFT + RIGHT + TOP + BOTTOM + WIDTH + HEIGHT

    def __init__(self, client: TelegramClient):
        super().__init__(client)

    async def on_new_message(self, message: Message):
        # If a message has text saying to crop, some percentages maybe?
        # And is a reply to a video, then crop it
        text_clean = message.text.lower().strip()
        if not text_clean.startswith("crop"):
            return
        crop_string = self.parse_crop_input(text_clean[len("crop"):].strip())
        if crop_string is None:
            return [await self.send_text_reply(
                message,
                "I don't understand this crop command. "
                "Please specify what percentage to cut off the left, right, top, bottom. "
                "Alternatively specify the desired percentage for the width and height. "
                "Use the format `crop left 20% right 20% top 10%`."
            )]
        video = find_video_for_message(message)
        if video is None:
            return [await self.send_text_reply(message, "I'm not sure which video you would like to crop.")]
        output_path = random_sandbox_video_path()
        async with self.progress_message(message, "Cropping video"):
            ff = ffmpy3.FFmpeg(
                inputs={video.full_path: None},
                outputs={output_path: f"-filter:v \"{crop_string}\" -c:a copy"}
            )
            await ff.run_async()
            await ff.wait()
            return [await self.send_video_reply(message, output_path)]

    def parse_crop_input(self, input_clean: str) -> Optional[str]:
        input_split = re.split(r"[\s:=]", input_clean)
        if len(input_split) % 2 != 0:
            return None
        left, right, top, bottom, width, height = None, None, None, None, None, None
        for i in range(len(input_split)//2):
            a, b = input_split[2*i], input_split[(2*i)+1]
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
        return f"crop=in_w*{width/100:.2f}:in_h*{height/100:.2f}:in_w*{left/100:.2f}:in_h*{top/100:.2f}"


# noinspection PyUnresolvedReferences
class StabiliseHelper(Helper):

    async def on_new_message(self, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.lower().strip()
        if text_clean not in ["stabilise", "stabilize", "stab", "deshake", "unshake"]:
            return
        video = find_video_for_message(message)
        if video is None:
            return [await self.send_text_reply(message, "I'm not sure which video you would like to stabilise.")]
        output_path = random_sandbox_video_path()
        async with self.progress_message(message, "Stabilising video"):
            ff = ffmpy3.FFmpeg(
                inputs={video.full_path: None},
                outputs={output_path: "-vf deshake"}
            )
            await ff.run_async()
            await ff.wait()
            return [await self.send_video_reply(message, output_path)]


# noinspection PyUnresolvedReferences
class QualityVideoHelper(Helper):

    async def on_new_message(self, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.lower().strip()
        if text_clean != "video":
            return
        video = find_video_for_message(message)
        if video is None:
            return [await self.send_text_reply(message, "I'm not sure which video you want to video.")]
        output_path = random_sandbox_video_path()
        async with self.progress_message(message, "Converting video into video"):
            if not await self.video_has_audio_track(video):
                ff = ffmpy3.FFmpeg(
                    global_options=["-f lavfi"],
                    inputs={
                        "aevalsrc=0": None,
                        video.full_path: None
                    },
                    outputs={output_path: "-qscale:v 0 -acodec aac -map 0:0 -map 1:0 -shortest"}
                )
            else:
                ff = ffmpy3.FFmpeg(
                    inputs={video.full_path: None},
                    outputs={output_path: "-qscale 0"}
                )
            await ff.run_async()
            await ff.wait()
            return [await self.send_video_reply(message, output_path)]

    async def video_has_audio_track(self, video: Video):
        ffprobe = ffmpy3.FFprobe(
            global_options=["-v error"],
            inputs={video.full_path: "-show_streams -select_streams a -loglevel error"}
        )
        ffprobe_process = await ffprobe.run_async(stdout=subprocess.PIPE)
        ffprobe_out = await ffprobe_process.communicate()
        await ffprobe.wait()
        output = ffprobe_out[0].decode('utf-8').strip()
        return len(output) != 0


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
