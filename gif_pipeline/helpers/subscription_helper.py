from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, TYPE_CHECKING

import isodate

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.database import Database, SubscriptionData
    from gif_pipeline.tasks.task_worker import TaskWorker
    from gif_pipeline.telegram_client import TelegramClient


class SubscriptionException(Exception):
    pass


class SubscriptionHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)
        self.subscriptions = load_subs_from_database(database)

    def initialise(self):
        pass  # TODO: Scheduler and stuff

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.lower().strip()
        if not text_clean.startswith("subscribe"):
            return None
        split_text = message.text.split()
        if len(split_text) < 2:
            return [await self.send_text_reply(chat, message, "Please specify a feed link to subscribe to.")]
        feed_link = split_text[1]
        subscription = create_sub_for_link(feed_link, chat.chat_data.chat_id)
        self.subscriptions.append(subscription)
        self.save_subscriptions()
        return [await self.send_text_reply(chat, message, f"Added subscription for {feed_link}")]

    def save_subscriptions(self):
        for subscription in self.subscriptions:
            new_sub = subscription.subscription_id is None
            saved_data = self.database.save_subscription(subscription.to_data(), subscription.seen_item_ids)
            if new_sub:
                subscription.subscription_id = saved_data.subscription_id


def load_subs_from_database(database: Database) -> List["Subscription"]:
    sub_data = database.list_subscriptions()
    subscriptions = []
    for sub_entry in sub_data:
        seen_items = database.list_item_ids_for_subscription(sub_entry)
        subscription = create_sub_for_link(
            sub_entry.feed_link,
            sub_entry.chat_id,
            subscription_id=sub_entry.subscription_id,
            last_check_time=sub_entry.last_check_time,
            check_rate=sub_entry.check_rate,
            enabled=sub_entry.enabled,
            seen_item_ids=seen_items
        )
        if subscription is None:
            raise SubscriptionException(f"Failed to load subscription from database for: {sub_entry.feed_link}")
        subscriptions.append(subscription)
    return subscriptions


def create_sub_for_link(
        feed_link: str,
        chat_id: int,
        *,
        subscription_id: int = None,
        last_check_time: Optional[datetime] = None,
        check_rate: Optional[timedelta] = None,
        enabled: bool = True,
        seen_item_ids: Optional[List[str]] = None
) -> Optional["Subscription"]:
    sub_classes = []
    for sub_class in sub_classes:
        if sub_class.can_handle_link(feed_link):
            return Subscription(
                feed_link,
                chat_id,
                subscription_id=subscription_id,
                last_check_time=last_check_time,
                check_rate=check_rate,
                enabled=enabled,
                seen_item_ids=seen_item_ids
            )
    return None


class Subscription(ABC):

    def __init__(
            self,
            feed_url: str,
            chat_id: int,
            *,
            subscription_id: int = None,
            last_check_time: Optional[datetime] = None,
            check_rate: Optional[timedelta] = None,
            enabled: bool = True,
            seen_item_ids: Optional[List[str]] = None
    ):
        self.subscription_id = subscription_id
        self.chat_id = chat_id
        self.feed_url = feed_url
        self.last_check_time = last_check_time
        self.check_rate = check_rate or isodate.parse_duration("1h")
        self.enabled = enabled
        self.seen_item_ids = seen_item_ids or []

    @abstractmethod
    def check_for_new_items(self) -> List["Item"]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    def can_handle_link(cls, feed_link: str) -> bool:
        pass

    def to_data(self) -> SubscriptionData:
        return SubscriptionData(
            self.subscription_id,
            self.feed_url,
            self.chat_id,
            self.last_check_time.isoformat() if self.last_check_time else None,
            isodate.duration_isoformat(self.check_rate),
            self.enabled
        )


@dataclass
class Item:
    link: str
    title: Optional[str]
    file: Optional[str]
    is_video: bool = False
