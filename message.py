import datetime
import glob
import json
import logging
import os
import shutil
from typing import List, Optional

import dateutil.parser

from telegram_client import TelegramClient


class Message:
    history: List[str]
    FILE_NAME = "message.json"

    def __init__(self, channel: 'Group', message_id: int, posted: datetime):
        # Basic parameters
        self.channel = channel
        self.message_id = message_id
        self.datetime = posted  # type: datetime.datetime
        # Internal stuff
        self.directory = f"{channel.directory}{message_id:06}"
        self.video = None  # type: Optional[Video]
        self.history = []  # list of links to messages this has in history
        # Telegram message data
        self.chat_id = None  # type: int
        self.chat_username = None  # type: Optional[str]
        self.chat_title = None  # type: str
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

    @property
    def telegram_link(self) -> str:
        return self.channel.telegram_link_for_message(self)

    @staticmethod
    def from_directory(channel: 'Group', directory: str) -> Optional['Message']:
        message_id = int(directory.strip("/").split("/")[-1])
        with open(f"{directory}/{Message.FILE_NAME}", "r") as f:
            message_data = json.load(f)
        posted = dateutil.parser.parse(message_data["datetime"])
        message = Message(channel, message_id, posted)
        # Set all the optional parameters
        message.chat_id = message_data["chat"]["id"]
        message.chat_username = message_data["chat"]["username"]
        message.chat_title = message_data["chat"]["title"]
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
        # Load message history, if applicable
        if "history" in message_data:
            message.history = message_data["history"]
        return message

    @staticmethod
    async def from_telegram_message(channel: 'Group', message_data) -> 'Message':
        message_id = message_data.id
        posted = message_data.date
        message = Message(channel, message_id, posted)
        # Set all the optional parameters
        message.chat_id = message_data.chat_id
        chat = await message_data.get_chat()
        if hasattr(chat, "username"):
            message.chat_username = chat.username
        message.chat_title = chat.title
        message.text = message_data.text
        if message_data.forward is not None:
            message.is_forward = True
        if message_data.file is not None and message_data.web_preview is None:
            message.has_file = True
            message.file_mime_type = message_data.file.mime_type
            message.file_size = message_data.file.size
        # TODO: posted by
        if message_data.is_reply:
            message.is_reply = True
            message.reply_to_msg_id = message_data.reply_to_msg_id
        return message

    async def initialise_directory(self, client):
        os.makedirs(self.directory, exist_ok=True)
        if self.has_video:
            # Find video, if applicable
            self.video = Video.from_directory(self.directory)
            if self.video is None:
                self.video = await Video.from_message(self, client, self.directory)
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
            "reply_to": None,
            "history": self.history
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
        shutil.rmtree(self.directory)
        pass

    def extend_history_from(self, message: 'Message'):
        self.history = message.history + [message.telegram_link]

    def __repr__(self):
        return f"Message(chat_id={self.chat_username or self.chat_id}, message_id={self.message_id})"

    def __eq__(self, other):
        return isinstance(other, Message) and self.channel == other.channel and self.message_id == other.message_id

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return hash((self.channel.handle, self.message_id))


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

    def __init__(self, metadata: VideoMetaData, full_path: str):
        self.metadata = metadata
        self.full_path = full_path

    @staticmethod
    def from_directory(message_directory: str):
        video_files = glob.glob(f"{message_directory}/{Video.FILE_NAME}.*")
        metadata_path = f"{message_directory}/{VideoMetaData.FILE_NAME}"
        if video_files and os.path.exists(metadata_path):
            metadata = VideoMetaData.load_from_json(metadata_path)
            return Video(metadata, video_files[0])
        elif video_files:
            video_metadata = VideoMetaData(message_directory)
            video_metadata.save_to_json()
            return Video(video_metadata, video_files[0])
        else:
            return None

    @staticmethod
    async def from_message(message: Message, client: TelegramClient, message_directory: str):
        file_ext = message.file_mime_type.split("/")[-1]
        video_path = f"{message_directory}/{Video.FILE_NAME}.{file_ext}"
        if not os.path.exists(video_path):
            logging.info("Downloading video from message: {}".format(message))
            await client.download_media(message.chat_id, message.message_id, video_path)
            video_metadata = VideoMetaData(message_directory)
            video_metadata.save_to_json()
            return Video(video_metadata, video_path)
        else:
            return Video.from_directory(message_directory)
