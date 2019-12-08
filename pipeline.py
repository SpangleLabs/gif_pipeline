import json
import logging
import os
from typing import Dict

import telethon


class TelegramClient:
    def __init__(self, api_id, api_hash):
        self.client = telethon.TelegramClient('duplicate_checker', api_id, api_hash)
        self.client.start()

    async def iter_channel_messages(self, channel_handle: str):
        channel_entity = await self.client.get_entity(channel_handle)
        return self.client.iter_messages(channel_entity)

    async def download_media(self, message, path):
        return self.client.download_media(message=message, file=path)


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


class Pipeline:
    def __init__(self, config: Dict):
        self.channels = [Channel.from_json(x) for x in config['channels']]
        self.workshop = config['workshop_group']
        self.client = TelegramClient(config['api_id'], config['api_hash'])

    def initialise_channels(self):
        # Scrape channels
        for channel in self.channels:
            channel.create_directory()
            channel.initialise_videos(self.client)

    def initialise_duplicate_detector(self):
        pass

    def watch_workshop(self):
        pass


if __name__ == "__main__":
    with open("config.json", "r") as c:
        conf = json.load(c)
    pipeline = Pipeline(conf)
    pipeline.initialise_channels()
    pipeline.initialise_duplicate_detector()
    pipeline.watch_workshop()