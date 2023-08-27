import asyncio
import random
import logging
from dataclasses import dataclass
from datetime import timedelta, datetime, timezone
from typing import Optional, List, TYPE_CHECKING, Dict

from gif_pipeline.chat import Chat, Channel
from gif_pipeline.chat_config import ScheduleOrder
from gif_pipeline.helpers.helpers import Helper, find_video_for_message
from gif_pipeline.helpers.menus.schedule_reminder_menu import ScheduleReminderMenu, next_video_from_list

if TYPE_CHECKING:
    from gif_pipeline.database import Database
    from gif_pipeline.helpers.delete_helper import DeleteHelper
    from gif_pipeline.helpers.menu_helper import MenuHelper
    from gif_pipeline.helpers.send_helper import GifSendHelper
    from gif_pipeline.message import Message
    from gif_pipeline.tag_manager import TagManager
    from gif_pipeline.tasks.task_worker import TaskWorker
    from gif_pipeline.telegram_client import TelegramClient


logger = logging.getLogger(__name__)


@dataclass
class DelayRange:
    min_delay: timedelta
    max_delay: Optional[timedelta]

    @classmethod
    def from_midpoint(cls, midpoint: timedelta, variability_parcent: int) -> "DelayRange":
        min_delay = midpoint * ((100 - variability_parcent) / 100)
        max_delay = midpoint * ((100 + variability_parcent) / 100)
        return cls(min_delay, max_delay)
    
    def cap_min(self, min_delay: timedelta, variability_parcent: int) -> "DelayRange":
        if self.min_delay > min_delay:
            return self
        return DelayRange(
            min_delay,
            min_delay * ((100 + variability_parcent) / (100 - variability_parcent)),
        )
    
    def cap_max(self, max_delay: timedelta, variability_parcent: int) -> "DelayRange":
        if self.max_delay < max_delay:
            return self
        return DelayRange(
            max_delay * ((100 - variability_parcent) / (100 + variability_parcent)),
            max_delay,
        )
    
    def next_delay(self) -> timedelta:
        if not self.max_delay:
            return self.min_delay
        min_seconds = self.min_delay.total_seconds()
        max_seconds = self.max_delay.total_seconds()
        return timedelta(seconds=random.uniform(min_seconds, max_seconds))


def next_delay_for_channel_with_target(channel: 'Channel') -> timedelta:
    queue_length = channel.queue.count_videos()
    if queue_length == 0:
        return channel.schedule_config.min_time
    required_delay = channel.schedule_config.target_length / queue_length
    variability = channel.schedule_config.schedule_variability_percent
    delay_range = DelayRange.from_midpoint(required_delay, variability)
    delay_range = delay_range.cap_max(channel.schedule_config.max_time, variability)
    delay_range = delay_range.cap_min(channel.schedule_config.min_time, variability)
    return delay_range.next_delay()


def next_delay_for_channel(channel: 'Channel') -> timedelta:
    if channel.schedule_config.target_length:
        return next_delay_for_channel_with_target(channel)
    delay_range = DelayRange(
        channel.schedule_config.min_time,
        channel.schedule_config.max_time,
    )
    return delay_range.next_delay()


def next_post_time_for_channel(channel: 'Channel') -> datetime:
    time_delay = next_delay_for_channel(channel)
    last_post = channel.latest_message().message_data.datetime
    next_post_time = last_post + time_delay
    now = datetime.now(timezone.utc)
    if next_post_time < now:
        next_post_time = now + time_delay
    return next_post_time


def next_video_for_channel(channel: 'Channel') -> Optional['Message']:
    messages = []
    queue_messages = channel.queue.video_messages()
    if channel.schedule_config.order == ScheduleOrder.OLDEST_FIRST:
        messages = sorted(queue_messages, key=lambda msg: msg.message_data.datetime, reverse=False)
    if channel.schedule_config.order == ScheduleOrder.NEWEST_FIRST:
        messages = sorted(queue_messages, key=lambda msg: msg.message_data.datetime, reverse=False)
    if channel.schedule_config.order == ScheduleOrder.RANDOM:
        messages = random.sample(queue_messages, k=len(queue_messages))
    return next_video_from_list(messages)


@dataclass
class ScheduleReminderSentMenu:
    menu: 'ScheduleReminderMenu'
    msg: 'Message'


class ScheduleHelper(Helper):
    CHECK_DELAY = 60

    def __init__(
            self,
            database: 'Database',
            client: 'TelegramClient',
            worker: 'TaskWorker',
            channels: List['Channel'],
            menu_helper: 'MenuHelper',
            send_helper: 'GifSendHelper',
            delete_helper: 'DeleteHelper',
            tag_manager: 'TagManager'
    ):
        super().__init__(database, client, worker)
        self.channels = channels
        self.menu_helper = menu_helper
        self.menu_cache = menu_helper.menu_cache
        self.send_helper = send_helper
        self.delete_helper = delete_helper
        self.tag_manager = tag_manager

    async def on_new_message(self, chat: 'Chat', message: 'Message') -> Optional[List['Message']]:
        # If channel, update schedule time
        if isinstance(chat, Channel):
            return await self.update_reminder_by_channel(chat)
        if chat in [channel.queue for channel in self.channels] and message.has_video:
            return await self.update_reminder_by_queue(chat, message)
        # Manual schedule set command
        if message.text.strip().lower() != "schedule":
            return
        self.usage_counter.inc()
        video = find_video_for_message(chat, message)
        if not video:
            return [await self.send_text_reply(chat, message, "Please reply to the video you wish to schedule next.")]
        reminder_menus = self.reminder_menus()
        if chat.chat_data.chat_id not in reminder_menus:
            return [await self.send_text_reply(chat, message, "There is no schedule reminder menu in this chat.")]
        reminder_menu = reminder_menus[chat.chat_data.chat_id]
        await reminder_menu.menu.delete()
        reminder_menu.menu.video = video
        return [await reminder_menu.menu.send()]

    async def update_reminder_by_channel(self, chat: 'Channel') -> Optional[List['Message']]:
        if not chat.schedule_config:
            return None
        reminder_menus = self.reminder_menus()
        queue_chat_id = chat.queue.chat_data.chat_id
        if queue_chat_id not in reminder_menus:
            return None
        menu = reminder_menus[queue_chat_id]
        menu.menu.post_time = next_post_time_for_channel(chat)
        return [await menu.menu.send()]

    async def update_reminder_by_queue(self, chat: 'Chat', message: 'Message') -> Optional[List['Message']]:
        if not message.has_video:
            return None
        reminder_menus = self.reminder_menus()
        if chat.chat_data.chat_id not in reminder_menus:
            return None
        menu = reminder_menus[chat.chat_data.chat_id]
        return [await menu.menu.repost()]

    def reminder_menus(self) -> Dict[int, ScheduleReminderSentMenu]:
        schedule_menus = {}
        my_menu_classes = [ScheduleReminderMenu]
        for menu_entry in self.menu_cache.list_entries():
            sent_menu = menu_entry.sent_menu
            if any(isinstance(sent_menu.menu, klass) for klass in my_menu_classes):
                schedule_menus[menu_entry.chat_id] = ScheduleReminderSentMenu(sent_menu.menu, sent_menu.msg)
        return schedule_menus

    async def init_post_startup(self) -> None:
        reminder_menus = self.reminder_menus()
        new_menus = []
        for channel in self.channels:
            # Check if they have a reminder menu
            if channel.queue and channel.queue.chat_data.chat_id in reminder_menus:
                continue
            # Initialise channel
            menu_msg = await self.initialise_channel(channel)
            if menu_msg is not None:
                new_menus.append(menu_msg)
        asyncio.get_event_loop().create_task(self.scheduler())
        await super().init_post_startup()

    async def initialise_channel(self, channel: 'Channel') -> Optional['Message']:
        if not channel.schedule_config:
            return None
        # Figure out when message should be
        next_post_time = next_post_time_for_channel(channel)
        # Select video
        video = next_video_for_channel(channel)
        if video is None:
            empty_queue_text = "This queue is empty"
            if channel.queue.latest_message().text == empty_queue_text:
                return None
            logger.info(f"Queue is empty for channel: {channel}")
            return await self.send_message(channel.queue, text=empty_queue_text)
        # Create reminder
        logger.info(f"Initialising schedule reminder in channel: {channel}")
        return await self.menu_helper.schedule_reminder_menu(
            channel.queue,
            video,
            next_post_time,
            channel,
            self.send_helper
        )

    async def scheduler(self):
        while True:
            try:
                await self.check_channels()
            except Exception as e:
                logger.error("Failed to check channels, due to exception: ", exc_info=e)
            await asyncio.sleep(self.CHECK_DELAY)

    async def check_channels(self) -> Optional[List['Message']]:
        logger.info("Checking channel queues")
        reminder_menus = self.reminder_menus()
        for channel in self.channels:
            try:
                if not channel.queue or not channel.schedule_config:
                    continue
                if channel.queue.chat_data.chat_id not in reminder_menus:
                    await self.initialise_channel(channel)
                    continue
                sent_menu = reminder_menus[channel.queue.chat_data.chat_id]
                menu = sent_menu.menu
                if datetime.now(timezone.utc) > menu.post_time:
                    if menu.auto_post:
                        tags = menu.video.tags(self.database)
                        hashes = set(self.database.get_hashes_for_message(menu.video.message_data))
                        chan_msg = [await self.send_message(
                            channel, video_path=menu.video.message_data.file_path, tags=tags, video_hashes=hashes
                        )]
                        self.send_helper.send_tweet_if_applicable(channel, menu.video.message_data.file_path, tags)
                        await self.delete_helper.delete_family(channel.queue, menu.video)
                        return chan_msg
                    msgs = []
                    if menu.chat.count_videos() == 1:
                        msgs.append(
                            await self.send_text_reply(menu.chat, menu.video, "This is the only video in the queue")
                        )
                    msgs.append(await self.menu_helper.confirmation_menu(
                        menu.chat, None, menu.video, self.send_helper, channel
                    ))
                    return msgs
            except Exception as e:
                logger.error("Failed to check channel: %s due to exception: ", channel, exc_info=e)
