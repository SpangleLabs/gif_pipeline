from __future__ import annotations

import datetime
import logging
import os
from typing import Optional
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from telegram_client import TelegramClient
    from gif_pipeline.database import Database
    from gif_pipeline.group import ChatData


def mime_type_is_video(mime_type: str) -> bool:
    return mime_type.startswith("video") or mime_type == "image/gif"


class MessageData:
    def __init__(
            self,
            chat_id: int,
            message_id: int,
            msg_datetime: datetime.datetime,
            text: str,
            is_forward: bool,
            has_file: bool,
            file_path: Optional[str],
            file_mime_type: Optional[str],
            reply_to: Optional[int],
            sender_id: int,
            is_scheduled: bool
    ):
        self.chat_id = chat_id
        self.message_id = message_id
        self.datetime = msg_datetime
        self.text = text
        self.is_forward = is_forward
        self.has_file = has_file
        self.file_path = file_path
        self.file_mime_type = file_mime_type
        self.reply_to = reply_to
        self.sender_id = sender_id
        self.is_scheduled = is_scheduled

    def __repr__(self) -> str:
        return f"MessageData(chat_id={self.chat_id or self.chat_id}, message_id={self.message_id})"

    def __eq__(self, other: object) -> bool:
        return \
            isinstance(other, MessageData) \
            and self.chat_id == other.chat_id \
            and self.message_id == other.message_id \
            and self.is_scheduled == other.is_scheduled

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash((self.chat_id, self.message_id, self.is_scheduled))

    def expected_file_path(self, chat_data: ChatData):
        file_ext = self.file_mime_type.split("/")[-1]
        file_name = f"{'scheduled-' if self.is_scheduled else ''}{self.message_id:06}.{file_ext}"
        return f"{chat_data.directory}{file_name}"

    @property
    def has_video(self) -> bool:
        return self.has_file and mime_type_is_video(self.file_mime_type)


class Message:

    def __init__(self, message_data: MessageData, chat_data: ChatData):
        self.chat_data = chat_data
        self.message_data = message_data

    @property
    def has_video(self) -> bool:
        return self.message_data.has_video

    @property
    def telegram_link(self) -> str:
        return self.chat_data.telegram_link_for_message(self.message_data)

    @property
    def text(self) -> str:
        return self.message_data.text

    @classmethod
    async def from_message_data(cls, message_data: MessageData, chat_data: 'ChatData', client: 'TelegramClient'):
        if message_data.has_file:
            if message_data.file_path is None:
                video_path = message_data.expected_file_path(chat_data)
                if not os.path.exists(video_path):
                    logging.info(f"Downloading video from message: {message_data}")
                    await client.download_media(message_data.chat_id, message_data.message_id, video_path)
                message_data.file_path = video_path
            else:
                if not os.path.exists(message_data.file_path):
                    logging.info(f"Downloading video from message: {message_data}")
                    await client.download_media(message_data.chat_id, message_data.message_id, message_data.file_path)
        # Create message
        return Message(message_data, chat_data)

    def delete(self, database: 'Database') -> None:
        if self.message_data.file_path:
            try:
                os.remove(self.message_data.file_path)
            except OSError:
                pass
        database.remove_message(self.message_data)

    def __repr__(self) -> str:
        return f"Message({self.message_data})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Message) and self.message_data == other.message_data

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.message_data)
