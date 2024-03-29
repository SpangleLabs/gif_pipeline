from __future__ import annotations

import datetime
import logging
import os
from typing import Optional
from typing import TYPE_CHECKING

from gif_pipeline.video_tags import VideoTags

if TYPE_CHECKING:
    from telegram_client import TelegramClient
    from gif_pipeline.database import Database
    from gif_pipeline.chat_data import ChatData


logger = logging.getLogger(__name__)


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
            file_size: Optional[int],
            reply_to: Optional[int],
            sender_id: int,
            is_scheduled: bool,
            forwarded_channel_link: Optional[str] = None
    ):
        self.chat_id = chat_id
        self.message_id = message_id
        self.datetime = msg_datetime
        self.text = text
        self.is_forward = is_forward
        self.has_file = has_file
        self.file_path = file_path
        self.file_mime_type = file_mime_type
        self.file_size = file_size
        self.reply_to = reply_to
        self.sender_id = sender_id
        self.is_scheduled = is_scheduled
        self.forwarded_channel_link = forwarded_channel_link

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

    def expected_file_path(self, chat_data: ChatData) -> Optional[str]:
        if not self.has_file:
            return None
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
        self._tags = None

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
        logger.debug(f"Creating message: {message_data}")
        # Update file path if not set
        video_path = message_data.expected_file_path(chat_data)
        if video_path is not None and message_data.file_path is None:
            message_data.file_path = video_path
        # Ensure file data is blank, if it has no file
        if not message_data.has_file and message_data.file_path:
            message_data.file_path = None
            message_data.file_size = None
            message_data.file_mime_type = None
        # Download file if necessary
        if cls.needs_download(message_data):
            logger.info(f"Downloading video from message: {message_data}")
            await client.download_media(message_data.chat_id, message_data.message_id, video_path)
        # Create message
        return Message(message_data, chat_data)

    @classmethod
    def needs_download(cls, message_data: MessageData) -> bool:
        if message_data.has_file:
            if message_data.file_path is None:
                logger.info(f"Download required: file path unset for message: {message_data}")
                return True
            else:
                if not os.path.exists(message_data.file_path):
                    logger.info(f"Download required: file missing for message: {message_data}")
                    return True
                if message_data.file_mime_type == "image/jpeg":
                    # Telegram reports the wrong size for images, for some reason, so skip those
                    return False
                size_on_disc = os.path.getsize(message_data.file_path)
                if size_on_disc != message_data.file_size:
                    logger.info(
                        f"Download required: file is the wrong size for message: {message_data}. "
                        f"{size_on_disc}b locally, {message_data.file_size}b according to Telegram"
                    )
                    return True
        return False

    def delete(self, database: 'Database') -> None:
        if self.message_data.file_path:
            try:
                os.remove(self.message_data.file_path)
            except OSError:
                pass
        database.remove_message(self.message_data)

    def tags(self, database: 'Database') -> VideoTags:
        if not self._tags:
            tag_entries = database.get_tags_for_message(self.message_data)
            self._tags = VideoTags.from_database(tag_entries)
        return self._tags

    def __repr__(self) -> str:
        return f"Message({self.message_data})"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Message) and self.message_data == other.message_data

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def __hash__(self) -> int:
        return hash(self.message_data)
