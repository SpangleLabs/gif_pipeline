from __future__ import annotations

import asyncio
import logging
import os
from abc import ABC
from typing import TYPE_CHECKING, Awaitable
from typing import TypeVar, List, Optional

from prometheus_client.metrics import Gauge, Counter

from gif_pipeline.chat_config import ChatConfig, ChannelConfig, WorkshopConfig, ScheduleConfig
from gif_pipeline.chat_data import ChatData, ChannelData, WorkshopData
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.telegram_client import TelegramClient
    from gif_pipeline.database import Database
    from gif_pipeline.message import MessageData
T = TypeVar('T', bound='Group')


logger = logging.getLogger(__name__)

video_count = Gauge(
    "gif_pipeline_chat_video_count",
    "Number of videos in the chat, which can go up and down",
    labelnames=["chat_type", "chat_title"]
)
file_size_total = Gauge(
    "gif_pipeline_chat_total_file_size_bytes",
    "Total combined size of all files in a given chat, in bytes",
    labelnames=["chat_type", "chat_title"]
)
subscriber_count = Gauge(
    "gif_pipeline_channel_subscriber_count",
    "Number of subscribers in the channel",
    labelnames=["chat_title"]
)
workshop_new_message_count = Counter(
    "gif_pipeline_workshop_new_message_count",
    "Number of new messages posted in the workshop",
    labelnames=["chat_title"]
)
queue_duration = Gauge(
    "gif_pipeline_queue_est_duration_seconds",
    "Estimated duration of queue, based on schedule and videos in queue",
    labelnames=["chat_title"]
)


class Chat(ABC):
    def __init__(
            self,
            chat_data: ChatData,
            config: ChatConfig,
            messages: List[Message],
            client: TelegramClient
    ):
        self.chat_data = chat_data
        self.config = config
        self.messages = messages
        self.client = client
        self.init_metrics()

    def init_metrics(self) -> None:
        video_count.labels(
            chat_type=self.__class__.__name__,
            chat_title=self.chat_data.title
        ).set_function(lambda: self.count_videos())
        file_size_total.labels(
            chat_type=self.__class__.__name__,
            chat_title=self.chat_data.title
        ).set_function(lambda: self.sum_file_size())

    @staticmethod
    async def list_message_initialisers(
            chat_data: 'ChatData',
            config: 'ChatConfig',
            client: TelegramClient,
            database: 'Database',
    ) -> List[Awaitable[Message]]:
        logger.info(f"Initialising chat: {config}")
        # Ensure bot is in chat
        if not config.read_only:
            await client.invite_pipeline_bot_to_chat(chat_data)
        # Get messages from database and channel, ensure they match
        database_messages = database.list_messages_for_chat(chat_data)
        channel_messages = [m async for m in client.iter_channel_messages(chat_data, not config.read_only)]
        new_messages = set(channel_messages) - set(database_messages)
        removed_messages = set(database_messages) - set(channel_messages)
        for message_data in new_messages:
            database.save_message(message_data)
        for message_data in removed_messages:
            database.remove_message(message_data)

        # Check files, turn message data into message objects
        async def save_message(message):
            old_file_path = message.file_path
            new_message = await Message.from_message_data(message, chat_data, client)
            if old_file_path != new_message.message_data.file_path:
                database.save_message(new_message.message_data)
            return new_message

        return [save_message(message) for message in channel_messages]

    def cleanup_excess_files(self):
        # Check for extra files which need removing
        dir_files = os.listdir(self.chat_data.directory)
        msg_files = [msg.message_data.file_path for msg in self.messages]
        excess_files = set(dir_files) - set(msg_files)
        for file in excess_files:
            try:
                os.unlink(file)
            except OSError:
                pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.chat_data.title})"

    def count_videos(self) -> int:
        return len([True for msg in self.messages if msg.has_video])

    def sum_file_size(self) -> int:
        return sum([msg.message_data.file_size for msg in self.messages if msg.message_data.has_file])

    def remove_message(self, message_data: MessageData) -> None:
        self.messages = [msg for msg in self.messages if msg.message_data != message_data]

    def message_by_id(self, message_id: Optional[int]) -> Optional[Message]:
        if message_id is None:
            return None
        return next(iter([msg for msg in self.messages if msg.message_data.message_id == message_id]), None)

    def message_by_link(self, link: str) -> Optional[Message]:
        return next(iter([msg for msg in self.messages if msg.telegram_link == link]), None)

    def add_message(self, message: Message) -> None:
        self.messages.append(message)

    def latest_message(self) -> Optional[Message]:
        return next(iter(sorted(self.messages, key=lambda msg: msg.message_data.datetime, reverse=True)))

    @property
    def has_twitter(self) -> bool:
        return False


class Channel(Chat):

    def __init__(
            self,
            chat_data: ChannelData,
            config: ChannelConfig,
            messages: List[Message],
            client: TelegramClient,
            queue: Optional[WorkshopGroup] = None
    ):
        super().__init__(chat_data, config, messages, client)
        self.config = config
        self.queue = queue
        self.sub_count = subscriber_count.labels(
            chat_title=self.chat_data.title
        )
        self.queue_duration = None
        if self.config.queue is not None and self.config.queue.schedule is not None:
            self.queue_duration = queue_duration.labels(
                chat_title=self.chat_data.title
            ).set_function(lambda: self.config.queue.schedule.avg_time.total_seconds() * self.queue.count_videos())
        asyncio.ensure_future(self.periodically_update_sub_count())

    async def periodically_update_sub_count(self) -> None:
        logger.info("Starting subscription metric updater")
        while True:
            logger.info("Checking subscriber count")
            await self.update_sub_count()
            await asyncio.sleep(60*60)

    async def update_sub_count(self) -> None:
        sub_count = await self.client.get_subscriber_count(self.chat_data)
        logger.info(f"Subscribers: {sub_count}")
        self.sub_count.set(sub_count)

    @property
    def has_queue(self) -> bool:
        return self.config.queue is not None

    @property
    def has_twitter(self) -> bool:
        return self.config.twitter_config is not None

    @property
    def schedule_config(self) -> Optional[ScheduleConfig]:
        if self.config.queue is None:
            return None
        return self.config.queue.schedule


class WorkshopGroup(Chat):

    def __init__(
            self,
            chat_data: WorkshopData,
            config: WorkshopConfig,
            messages: List[Message],
            client: TelegramClient
    ):
        super().__init__(chat_data, config, messages, client)
        self.new_message_count = workshop_new_message_count.labels(
            chat_title=self.chat_data.title
        )

    def add_message(self, message: Message) -> None:
        self.new_message_count.inc()
        super().add_message(message)
