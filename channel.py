import glob
import json
import logging
import os
from typing import Dict

from telegram_client import TelegramClient


class Channel:
    def __init__(self, handle: str, queue: bool = False):
        self.handle = handle
        self.queue = queue
        self.channel_directory = f"store/channels/{self.handle}/"
        self.messages = {}
        self.create_directory()

    @staticmethod
    def from_json(json_dict) -> 'Channel':
        return Channel(json_dict['handle'], json_dict['queue'])

    def create_directory(self):
        os.makedirs(self.channel_directory, exist_ok=True)

    def initialise_channel(self, client: TelegramClient):
        directory_messages = self.read_messages_from_directory()
        channel_messages = self.read_messages_from_channel(client)
        new_messages = [msg_id for msg_id in channel_messages.keys() if msg_id not in directory_messages]
        removed_messages = [msg_id for msg_id in directory_messages.keys() if msg_id not in channel_messages]
        for msg_id in new_messages:
            channel_messages[msg_id].initialise_directory(client)
        for msg_id in removed_messages:
            directory_messages[msg_id].delete_directory()
        self.messages = channel_messages

    def read_messages_from_directory(self) -> Dict[int, 'Message']:
        messages = {}
        # List subdirectories in directory and populate messages list
        subdirectories = [
            f"{self.channel_directory}{message_dir}"
            for message_dir
            in os.listdir(self.channel_directory)
            if os.path.isdir(message_dir)
        ]
        for subdirectory in subdirectories:
            message = Message.from_directory(self, subdirectory)
            messages[message.message_id] = message
        return messages

    def read_messages_from_channel(self, client: TelegramClient) -> Dict[int, 'Message']:
        new_messages = {}
        for message_data in client.iter_channel_messages(self.handle):
            message = Message.from_telegram_message(self, message_data)
            new_messages[message.message_id] = message
        return new_messages


class Message:
    def __init__(self, channel: Channel, message_id: int):
        self.channel = channel
        self.message_id = message_id
        self.directory = f"{channel.channel_directory}{message_id:06}"
        self.message_data = None
        self.video = None

    @staticmethod
    def from_directory(channel: Channel, directory: str) -> 'Message':
        message_id = int(directory.strip("/").split("/")[-1])
        message = Message(channel, message_id)
        return message

    @staticmethod
    def from_telegram_message(channel: Channel, message_data) -> 'Message':
        message_id = message_data.id
        message = Message(channel, message_id)
        message.message_data = message_data
        return message

    def initialise_directory(self, client):
        os.makedirs(self.directory, exist_ok=True)
        if self.message_data and self.message_data.file:
            # Find video, if applicable
            self.video = Video.from_message(self.message_data, client, self.directory)
        else:
            # Find video, if applicable
            self.video = Video.from_directory(self.directory)

    def delete_directory(self):
        os.removedirs(self.directory)
        pass


class VideoMetaData:
    FILE_NAME = "video_metadata.json"

    def __init__(self, video_directory: str):
        self.video_directory = video_directory
        self.message_link = None
        self.message_posted = None
        self.source_type = None
        self.source_data = dict()
        self.history = []

    def save_to_json(self):
        file_path = f"{self.video_directory}/{VideoMetaData.FILE_NAME}"
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
    FILE_NAME = "video"

    def __init__(self, metadata: VideoMetaData):
        self.metadata = metadata

    @staticmethod
    def from_directory(message_directory: str):
        video_files = glob.glob(f"{message_directory}/{Video.FILE_NAME}.*")
        video_metadata_files = glob.glob(f"{message_directory}/{VideoMetaData.FILE_NAME}")
        if video_files and video_metadata_files:
            metadata_path = f"{message_directory}/{VideoMetaData.FILE_NAME}"
            metadata = VideoMetaData.load_from_json(metadata_path)
            return Video(metadata)
        else:
            return None

    @staticmethod
    def from_message(message, client: TelegramClient, message_directory: str):
        file_ext = message.file.mime_type.split("/")[-1]
        video_path = f"{message_directory}/{Video.FILE_NAME}.{file_ext}"
        if not os.path.exists(video_path):
            logging.info("Downloading message: {}".format(message))
            client.download_media(message, video_path)
            video_metadata = VideoMetaData(message_directory)
            video_metadata.save_to_json()
            return Video(video_metadata)
        else:
            return Video.from_directory(message_directory)
