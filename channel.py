import json
import logging
import os

from telegram_client import TelegramClient


class Channel:
    def __init__(self, handle: str, queue: bool = False):
        self.handle = handle
        self.queue = queue
        self.channel_directory = f"store/channels/{self.handle}/"
        self.videos = []

    @staticmethod
    def from_json(json_dict):
        return Channel(json_dict['handle'], json_dict['queue'])

    def create_directory(self):
        os.makedirs(self.channel_directory, exist_ok=True)

    async def initialise_videos(self, client: TelegramClient):
        for message in await client.iter_channel_messages(self.handle):
            if message.file is None:
                continue
            self.videos.append(Video.from_message(message, client, self.channel_directory))


class VideoMetaData:
    def __init__(self, video_directory: str):
        self.video_directory = video_directory
        self.message_link = None
        self.message_posted = None
        self.source_type = None
        self.source_data = dict()
        self.history = []

    def save_to_json(self):
        file_path = f"{self.video_directory}/metadata.json"
        with open(file_path, "w+") as f:
            json.dump({
                "video_directory": self.video_directory,
                "message_link": self.message_link,
                "message_posted": self.message_posted
            }, f)

    @staticmethod
    def load_from_json(file_path: str):
        with open(file_path, "r") as f:
            json_dict = json.load(f)
        return VideoMetaData(json_dict['video_directory'])


class Video:
    def __init__(self, metadata: VideoMetaData):
        self.metadata = metadata

    @staticmethod
    def from_directory(video_directory: str):
        metadata_path = f"{video_directory}/metadata.json"
        metadata = VideoMetaData.load_from_json(metadata_path)
        return Video(metadata)

    @staticmethod
    def from_message(message, client: TelegramClient, channel_directory: str):
        file_ext = message.file.mime_type.split("/")[-1]
        video_directory = f"{channel_directory}/{str(message.id):05d}/"
        if not os.path.exists(video_directory):
            video_path = f"{video_directory}/video.{file_ext}"
            logging.info("Downloading message: {}".format(message))
            client.download_media(message, video_path)
            video_metadata = VideoMetaData(video_directory)
            video_metadata.save_to_json()
            return Video(video_metadata)
        else:
            return Video.from_directory(video_directory)
