import random
from datetime import timedelta, datetime
from typing import Optional, List, TYPE_CHECKING, Dict

from gif_pipeline.chat_config import ScheduleOrder
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.helpers.menus.schedule_reminder_menu import ScheduleReminderMenu

if TYPE_CHECKING:
    from gif_pipeline.message import Message
    from gif_pipeline.chat import Chat, Channel
    from gif_pipeline.database import Database
    from gif_pipeline.telegram_client import TelegramClient
    from gif_pipeline.tasks.task_worker import TaskWorker
    from gif_pipeline.helpers.menu_helper import MenuHelper


def next_post_time_for_channel(channel: Channel) -> datetime:
    time_delay = channel.schedule_config.min_time
    if channel.schedule_config.max_time:
        min_seconds = channel.schedule_config.min_time.total_seconds()
        max_seconds = channel.schedule_config.max_time.total_seconds()
        time_delay = timedelta(seconds=random.uniform(min_seconds, max_seconds))
    last_post = channel.latest_message().message_data.datetime
    next_post_time = last_post + time_delay
    now = datetime.utcnow()
    if next_post_time < now:
        # TODO: Maybe always use this?
        next_post_time = now + time_delay
    return next_post_time


def next_video_for_channel(channel: Channel) -> Optional[Message]:
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


class ScheduleHelper(Helper):

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            channels: List[Channel],
            menu_helper: MenuHelper
    ):
        super().__init__(database, client, worker)
        self.channels = channels
        self.menu_helper = menu_helper
        self.menu_cache = menu_helper.menu_cache

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        if message.text.strip().lower() != "check schedules":
            return
        for channel in self.channels:
            if not channel.schedule_config:
                continue
        return [await self.send_text_reply(chat, message, "Mmm, schedules, yes.")]

    def reminder_menus(self) -> Dict[int, ScheduleReminderMenu]:
        schedule_menus = {}
        my_menu_classes = [ScheduleReminderMenu, QueueEmptyMenu]
        for menu_entry in self.menu_cache.list_entries():
            if any(isinstance(menu_entry.sent_menu.menu, klass) for klass in my_menu_classes):
                schedule_menus[menu_entry.chat_id] = menu_entry.sent_menu.menu
        return schedule_menus

    async def initialise(self) -> Optional[List[Message]]:
        reminder_menus = self.reminder_menus()
        new_menus = []
        for channel in self.channels:
            if not channel.schedule_config:
                continue
            # Check if they have a reminder menu
            if channel.queue.chat_data.chat_id in reminder_menus:
                continue
            # Figure out when message should be
            next_post_time = next_post_time_for_channel(channel)
            # Select video
            video = next_video_for_channel(channel)
            if video is None:
                # TODO: Check if queue empty has already been posted about
                await self.client.send_text_message(channel.chat_data, "This queue is empty")
            # Create reminder
            new_menus.append(await self.menu_helper.schedule_reminder_menu(
                channel.queue,
                video,
                next_post_time
            ))
        return new_menus
