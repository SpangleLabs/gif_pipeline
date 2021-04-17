import asyncio
import random
from dataclasses import dataclass
from datetime import timedelta, datetime, timezone
from threading import Thread
from typing import Optional, List, TYPE_CHECKING, Dict

from gif_pipeline.chat_config import ScheduleOrder
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.helpers.menus.schedule_reminder_menu import ScheduleReminderMenu

if TYPE_CHECKING:
    from gif_pipeline.helpers.send_helper import GifSendHelper
    from gif_pipeline.tag_manager import TagManager
    from gif_pipeline.message import Message
    from gif_pipeline.chat import Chat, Channel
    from gif_pipeline.database import Database
    from gif_pipeline.telegram_client import TelegramClient
    from gif_pipeline.tasks.task_worker import TaskWorker
    from gif_pipeline.helpers.menu_helper import MenuHelper


def next_post_time_for_channel(channel: 'Channel') -> datetime:
    time_delay = channel.schedule_config.min_time
    if channel.schedule_config.max_time:
        min_seconds = channel.schedule_config.min_time.total_seconds()
        max_seconds = channel.schedule_config.max_time.total_seconds()
        time_delay = timedelta(seconds=random.uniform(min_seconds, max_seconds))
    last_post = channel.latest_message().message_data.datetime
    next_post_time = last_post + time_delay
    now = datetime.now(timezone.utc)
    if next_post_time < now:
        # TODO: Maybe always use this?
        next_post_time = now + time_delay
    return next_post_time


def next_video_for_channel(channel: 'Channel') -> Optional['Message']:
    messages = []
    if channel.schedule_config.order == ScheduleOrder.OLDEST_FIRST:
        messages = sorted(channel.messages, key=lambda msg: msg.message_data.datetime, reverse=False)
    if channel.schedule_config.order == ScheduleOrder.NEWEST_FIRST:
        messages = sorted(channel.messages, key=lambda msg: msg.message_data.datetime, reverse=False)
    if channel.schedule_config.order == ScheduleOrder.RANDOM:
        messages = random.sample(channel.messages, k=len(channel.messages))
    video = None
    for message in messages:
        if not message.has_video:
            continue
        video = message
        break
    return video


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
            tag_manager: 'TagManager'
    ):
        super().__init__(database, client, worker)
        self.channels = channels
        self.menu_helper = menu_helper
        self.menu_cache = menu_helper.menu_cache
        self.send_helper = send_helper
        self.tag_manager = tag_manager
        self.scheduler_thread = None  # type: Optional[Thread]

    async def on_new_message(self, chat: 'Chat', message: 'Message') -> Optional[List['Message']]:
        if message.text.strip().lower() != "check schedules":
            return
        for channel in self.channels:
            if not channel.schedule_config:
                continue
        return [await self.send_text_reply(chat, message, "Mmm, schedules, yes.")]

    def reminder_menus(self) -> Dict[int, ScheduleReminderSentMenu]:
        schedule_menus = {}
        my_menu_classes = [ScheduleReminderMenu]
        for menu_entry in self.menu_cache.list_entries():
            sent_menu = menu_entry.sent_menu
            if any(isinstance(sent_menu.menu, klass) for klass in my_menu_classes):
                schedule_menus[menu_entry.chat_id] = ScheduleReminderSentMenu(sent_menu.menu, sent_menu.msg)
        return schedule_menus

    async def initialise(self) -> Optional[List['Message']]:
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
        self.scheduler_thread = Thread(target=asyncio.run, args=(self.scheduler(),))
        self.scheduler_thread.start()
        return new_menus

    async def initialise_channel(self, channel: 'Channel') -> Optional['Message']:
        if not channel.schedule_config:
            return None
        # Figure out when message should be
        next_post_time = next_post_time_for_channel(channel)
        # Select video
        video = next_video_for_channel(channel)
        if video is None:
            # TODO: Check if queue empty has already been posted about
            return await self.client.send_text_message(channel.chat_data, "This queue is empty")
        # Create reminder
        return await self.menu_helper.schedule_reminder_menu(
            channel.queue,
            video,
            next_post_time
        )

    async def scheduler(self):
        while True:
            await self.check_channels()
            await asyncio.sleep(self.CHECK_DELAY)

    async def check_channels(self):
        reminder_menus = self.reminder_menus()
        for channel in self.channels:
            if not channel.queue or not channel.schedule_config:
                continue
            if channel.queue.chat_data.chat_id not in reminder_menus:
                await self.initialise_channel(channel)
                continue
            sent_menu = reminder_menus[channel.queue.chat_data.chat_id]
            menu = sent_menu.menu
            if datetime.utcnow() > menu.post_time:
                menu.posted = True
                missing_tags = self.tag_manager.missing_tags_for_video(menu.video, channel, menu.chat)
                if missing_tags:
                    return await self.menu_helper.additional_tags_menu(
                        menu.chat, sent_menu.msg, menu.video, self.send_helper, channel, missing_tags
                    )
                return await self.menu_helper.confirmation_menu(
                    menu.chat, sent_menu.msg, menu.video, self.send_helper, channel
                )
