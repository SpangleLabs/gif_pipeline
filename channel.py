import datetime
import glob
import json
import logging
import os
from typing import Dict, Optional

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
        logging.info(f"Initialising channel: {self}")
        directory_messages = self.read_messages_from_directory()
        channel_messages = self.read_messages_from_channel(client)
        new_messages = [msg_id for msg_id in channel_messages.keys() if msg_id not in directory_messages]
        removed_messages = [msg_id for msg_id in directory_messages.keys() if msg_id not in channel_messages]
        logging.info(f"Channel: {self} has {len(new_messages)} new and {len(removed_messages)} removed messages")
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
            if os.path.isdir(f"{self.channel_directory}{message_dir}")
        ]
        for subdirectory in subdirectories:
            try:
                message = Message.from_directory(self, subdirectory)
                if message is not None:
                    messages[message.message_id] = message
            except Exception as e:
                logging.warning(f"Failed to read message from directory: {subdirectory}. Exception: ", exc_info=e)
        return messages

    def read_messages_from_channel(self, client: TelegramClient) -> Dict[int, 'Message']:
        new_messages = {}
        for message_data in client.iter_channel_messages(self.handle):
            message = Message.from_telegram_message(self, message_data)
            new_messages[message.message_id] = message
        return new_messages

    def __repr__(self):
        return f"Channel({self.handle})"


class Message:
    FILE_NAME = "message.json"

    def __init__(self, channel: Channel, message_id: int):
        # Basic parameters
        self.channel = channel
        self.message_id = message_id
        # Internal stuff
        self.directory = f"{channel.channel_directory}{message_id:06}"
        self.video = None
        # Telegram message data
        self.chat_id = None  # type: int
        self.chat_username = None  # type: str
        self.chat_title = None  # type: str
        self.datetime = None  # type: datetime.datetime
        self.text = None  # type: Optional[str]
        self.is_forward = False  # type: bool
        self.has_file = False  # type: bool
        self.file_mime_type = None  # type: Optional[str]
        self.file_size = None  # type: Optional[int]
        self.is_reply = False  # type: bool
        self.reply_to_msg_id = None  # type: Optional[int]

    @property
    def has_video(self) -> bool:
        return self.has_file and (self.file_mime_type.startswith("video") or self.file_mime_type == "image/gif")

    @staticmethod
    def from_directory(channel: Channel, directory: str) -> Optional['Message']:
        message_id = int(directory.strip("/").split("/")[-1])
        message = Message(channel, message_id)
        with open(f"{directory}/{Message.FILE_NAME}", "r") as f:
            message_data = json.load(f)
        message.chat_id = message_data["chat"]["id"]
        message.chat_username = message_data["chat"]["username"]
        message.chat_title = message_data["chat"]["title"]
        message.datetime = datetime.datetime.fromisoformat(message_data["datetime"])
        message.text = message_data["text"]
        message.is_forward = message_data["is_forward"]
        message.has_file = message_data["file"] is not None
        if message.has_file:
            message.file_mime_type = message_data["file"]["mime_type"]
            message.file_size = message_data["file"]["size"]
            if message.has_video:
                video = Video.from_directory(directory)
                if video is None:
                    return None
                message.video = video
        message.is_reply = message_data["reply_to"]
        if message.is_reply:
            message.reply_to_msg_id = message_data["reply_to"]["message_id"]
        return message

    @staticmethod
    def from_telegram_message(channel: Channel, message_data) -> 'Message':
        message_id = message_data.id
        message = Message(channel, message_id)
        message.chat_id = message_data.chat_id
        message.chat_username = message_data.chat.username
        message.chat_title = message_data.chat.title
        message.datetime = message_data.date
        message.text = message_data.text
        if message_data.forward is not None:
            message.is_forward = True
        if message_data.file is not None:
            message.has_file = True
            message.file_mime_type = message_data.file.mime_type
            message.file_size = message_data.file.size
        # TODO: posted by
        if message_data.is_reply:
            message.is_reply = True
            message.reply_to_msg_id = message_data.reply_to_msg_id
        return message

    def initialise_directory(self, client):
        os.makedirs(self.directory, exist_ok=True)
        if self.has_video:
            # Find video, if applicable
            self.video = Video.from_directory(self.directory)
            if self.video is None:
                self.video = Video.from_message(self, client, self.directory)
        # Save message data
        message_data = {
            "message_id": self.message_id,
            "chat": {
                "id": self.chat_id,
                "username": self.chat_username,
                "title": self.chat_title
            },
            "datetime": self.datetime.isoformat(),
            "text": self.text,
            "is_forward": self.is_forward,
            "file": None,
            "reply_to": None
        }
        if self.has_file:
            message_data["file"] = {
                "mime_type": self.file_mime_type,
                "size": self.file_size
            }
        if self.is_reply:
            message_data["reply_to"] = {
                "message_id": self.reply_to_msg_id
            }
        file_path = f"{self.directory}/{Message.FILE_NAME}"
        with open(file_path, "w+") as f:
            json.dump(message_data, f, indent=2)

    def delete_directory(self):
        os.removedirs(self.directory)
        pass

    def __repr__(self):
        return f"Message(chat_id={self.chat_username or self.chat_id}, message_id={self.message_id})"


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
            }, f, indent=2)

    @staticmethod
    def load_from_json(file_path: str):
        with open(file_path, "r") as f:
            json_dict = json.load(f)
        metadata = VideoMetaData(json_dict['video_directory'])
        metadata.message_link = json_dict["message_link"]
        metadata.message_posted = json_dict["message_posted"]
        return metadata


class Video:
    FILE_NAME = "video"

    def __init__(self, metadata: VideoMetaData):
        self.metadata = metadata

    @staticmethod
    def from_directory(message_directory: str):
        video_files = glob.glob(f"{message_directory}/{Video.FILE_NAME}.*")
        metadata_path = f"{message_directory}/{VideoMetaData.FILE_NAME}"
        if video_files and os.path.exists(metadata_path):
            metadata = VideoMetaData.load_from_json(metadata_path)
            return Video(metadata)
        else:
            return None

    @staticmethod
    def from_message(message: Message, client: TelegramClient, message_directory: str):
        file_ext = message.file_mime_type.split("/")[-1]
        video_path = f"{message_directory}/{Video.FILE_NAME}.{file_ext}"
        if not os.path.exists(video_path):
            logging.info("Downloading video from message: {}".format(message))
            client.download_media(message.chat_id, message.message_id, video_path)
            video_metadata = VideoMetaData(message_directory)
            video_metadata.save_to_json()
            return Video(video_metadata)
        else:
            return Video.from_directory(message_directory)
