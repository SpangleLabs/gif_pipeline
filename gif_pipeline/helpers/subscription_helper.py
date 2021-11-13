import asyncio
import glob
import json
import logging
import os
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from json import JSONDecodeError
from typing import List, Optional, TYPE_CHECKING, Type

import isodate
from prometheus_client import Counter, Gauge

from gif_pipeline.chat import Chat
from gif_pipeline.database import SubscriptionData
from gif_pipeline.helpers.helpers import Helper, random_sandbox_video_path
from gif_pipeline.helpers.duplicate_helper import hash_image
from gif_pipeline.helpers.video_helper import video_to_video
from gif_pipeline.message import Message
from gif_pipeline.tasks.youtube_dl_task import YoutubeDLDumpJsonTask
from gif_pipeline.video_tags import VideoTags

if TYPE_CHECKING:
    from gif_pipeline.database import Database
    from gif_pipeline.helpers.duplicate_helper import DuplicateHelper
    from gif_pipeline.helpers.download_helper import DownloadHelper
    from gif_pipeline.tasks.task_worker import TaskWorker
    from gif_pipeline.telegram_client import TelegramClient
    from gif_pipeline.pipeline import Pipeline

logger = logging.getLogger(__name__)

subscription_count = Gauge(
    "gif_pipeline_subscription_helper_subscription_count",
    "Number of active subscriptions in the subscription helper",
    labelnames=["subscription_class_name"]
)

subscription_posts = Counter(
    "gif_pipeline_subscription_helper_post_count_total",
    "Total number of posts sent by the subscription helper",
    labelnames=["subscription_class_name"]
)


class SubscriptionException(Exception):
    pass


class SubscriptionHelper(Helper):
    CHECK_DELAY = 60

    def __init__(
            self,
            database: "Database",
            client: "TelegramClient",
            worker: "TaskWorker",
            pipeline: "Pipeline",
            duplicate_helper: "DuplicateHelper",
            download_helper: "DownloadHelper"
    ):
        super().__init__(database, client, worker)
        self.pipeline = pipeline
        self.duplicate_helper = duplicate_helper
        self.download_helper = download_helper
        self.subscriptions: List[Subscription] = []
        self.sub_classes = [YoutubeDLSubscription]
        # Initialise counters
        for sub_class in self.sub_classes:
            # TODO: add metric labels for workshop titles
            subscription_count.labels(subscription_class_name=sub_class.__name__)
            subscription_posts.labels(subscription_class_name=sub_class.__name__)
            subscription_count.labels(subscription_class_name=sub_class.__name__).set_function(
                lambda: len([s for s in self.subscriptions if isinstance(s, sub_class)])
            )

    async def initialise(self) -> None:
        self.subscriptions = await load_subs_from_database(self.database, self)
        asyncio.get_event_loop().create_task(self.sub_checker())

    async def sub_checker(self) -> None:
        while True:
            try:
                await self.check_subscriptions()
            except Exception as e:
                logger.error(f"Failed to check subscriptions, due to exception: {e}")
            await asyncio.sleep(self.CHECK_DELAY)

    async def check_subscriptions(self) -> None:
        logger.info("Checking subscriptions")
        subscriptions = self.subscriptions[:]
        for subscription in subscriptions:
            if not subscription.needs_check():
                continue
            chat = self.pipeline.chat_by_id(subscription.chat_id)
            try:
                new_items = await subscription.check_for_new_items()
            except Exception as e:
                logger.error(f"Subscription to {subscription.feed_url} failed due to: {e}")
                await self.send_message(chat, text=f"Subscription to {subscription.feed_url} failed due to: {e}")
            else:
                for item in new_items:
                    try:
                        await self.post_item(item, subscription)
                    except Exception as e:
                        logger.error(f"Failed to post item {item.link} from {subscription.feed_url} feed due to: {e}")
                        await self.send_message(
                            chat,
                            text=f"Failed to post item {item.link} from {subscription.feed_url} feed due to: {e}"
                        )
            subscription.last_check_time = datetime.now()
            self.save_subscriptions()

    async def post_item(self, item: "Item", subscription: "Subscription"):
        subscription_posts.labels(subscription_class_name=subscription.__class__.__name__).inc()
        # Get chat
        chat = self.pipeline.chat_by_id(subscription.chat_id)
        # Construct caption
        caption = f"<a href=\"{item.link}\">{item.title}</a>\n\nFeed: {subscription.feed_url}"
        # If item has video and chat has duplicate detection
        hash_set = None
        tags = None
        if item.is_video:
            # Convert to video
            output_path = random_sandbox_video_path()
            tasks = video_to_video(item.file_path, output_path)
            for task in tasks:
                await self.worker.await_task(task)
            item.file_path = output_path
            # Check duplicate warnings
            if chat.config.duplicate_detection:
                warnings = await self.check_item_duplicate(item, subscription)
                if warnings:
                    caption += "\n\n" + "\n".join(warnings)
            # Build tags
            tags = VideoTags()
            tags.add_tag_value(VideoTags.source, item.link)
        # Post item
        await self.send_message(chat, text=caption, video_path=item.file_path, video_hashes=hash_set, tags=tags)

    async def check_item_duplicate(self, item: "Item", subscription: "Subscription") -> List[str]:
        # Hash video
        message_decompose_path = f"sandbox/decompose/subs/{subscription.subscription_id}-{item.item_id}/"
        # Decompose video into images
        os.makedirs(message_decompose_path, exist_ok=True)
        await self.duplicate_helper.decompose_video(item.file_path, message_decompose_path)
        # Hash the images
        image_files = glob.glob(f"{message_decompose_path}/*.png")
        hash_list = self.duplicate_helper.hash_pool.map(hash_image, image_files)
        hash_set = set(hash_list)
        # Delete the images
        try:
            shutil.rmtree(message_decompose_path)
        except FileNotFoundError:
            pass
        # Find duplicates
        has_blank_frame = self.duplicate_helper.blank_frame_hash in hash_set
        if has_blank_frame:
            hash_set.remove(self.duplicate_helper.blank_frame_hash)
        matching_messages = set(self.database.get_messages_for_hashes(hash_set))
        warnings = self.duplicate_helper.get_duplicate_warnings(matching_messages, has_blank_frame)
        return warnings

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        split_text = message.text.split()
        if not split_text[0].lower() in ["subscribe", "subscription", "sub", "subscriptions", "subs"]:
            return None
        self.usage_counter.inc()
        if len(split_text) < 2:
            return [await self.send_text_reply(chat, message, "Please specify a feed link to subscribe to.")]
        if split_text[1] in ["list"]:
            msg = "Subscriptions currently posting to this chat are:\n"
            msg += "\n".join(f"- {html.escape(sub.feed_url)}" for sub in self.subscriptions if sub.chat_id == chat.chat_data.chat_id)
            return [await self.send_text_reply(chat, message, msg)]
        if split_text[1] in ["remove", "delete"]:
            feed_link = split_text[2]
            feed_link_out = html.escape(feed_link)
            matching_sub = next([sub for sub in self.subscriptions if sub.feed_url == feed_link], None)
            if not matching_sub:
                return [await self.send_text_reply(
                    chat, message, f"Cannot remove subscription, as none match the feed link: {feed_link_out}"
                )]
            self.subscriptions.remove(matching_sub)
            self.save_subscriptions()
            return [await self.send_text_reply(chat, message, f"Removed subscription to {feed_link_out}")]
        feed_link = split_text[1]
        feed_link_out = html.escape(feed_link)
        # TODO: Allow specifying extra arguments?
        try:
            subscription = await create_sub_for_link(feed_link, chat.chat_data.chat_id, self, self.sub_classes)
            await subscription.check_for_new_items()
            self.subscriptions.append(subscription)
            self.save_subscriptions()
            return [await self.send_text_reply(chat, message, f"Added subscription for {feed_link_out}")]
        except Exception as e:
            logger.error(f"Failed to create subscription to {feed_link_out}", exc_info=e)
            return [await self.send_text_reply(
                chat, message,
                f"Could not add subscription to {feed_link_out}. Encountered error: {repr(e)}"
            )]

    def is_priority(self, chat: Chat, message: Message) -> bool:
        clean_args = message.text.strip().split()
        if not clean_args or clean_args[0].lower() not in ["subscribe"]:
            return False
        return True

    def save_subscriptions(self):
        for subscription in self.subscriptions:
            new_sub = subscription.subscription_id is None
            saved_data = self.database.save_subscription(subscription.to_data(), subscription.seen_item_ids)
            if new_sub:
                subscription.subscription_id = saved_data.subscription_id


async def load_subs_from_database(database: "Database", helper: SubscriptionHelper) -> List["Subscription"]:
    sub_data = database.list_subscriptions()
    subscriptions = []
    for sub_entry in sub_data:
        seen_items = database.list_item_ids_for_subscription(sub_entry)
        subscription = await create_sub_for_link(
            sub_entry.feed_link,
            sub_entry.chat_id,
            helper,
            helper.sub_classes,
            subscription_id=sub_entry.subscription_id,
            last_check_time=datetime.fromisoformat(sub_entry.last_check_time) if sub_entry.last_check_time else None,
            check_rate=isodate.parse_duration(sub_entry.check_rate),
            enabled=sub_entry.enabled,
            seen_item_ids=seen_items
        )
        if subscription is None:
            raise SubscriptionException(f"Failed to load subscription from database for: {sub_entry.feed_link}")
        subscriptions.append(subscription)
    return subscriptions


async def create_sub_for_link(
        feed_link: str,
        chat_id: int,
        helper: SubscriptionHelper,
        sub_classes: List[Type["Subscription"]],
        *,
        subscription_id: int = None,
        last_check_time: Optional[datetime] = None,
        check_rate: Optional[timedelta] = None,
        enabled: bool = True,
        seen_item_ids: Optional[List[str]] = None
) -> Optional["Subscription"]:
    for sub_class in sub_classes:
        if await sub_class.can_handle_link(feed_link, helper):
            return sub_class(
                feed_link,
                chat_id,
                helper,
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
            helper: SubscriptionHelper,
            *,
            subscription_id: int = None,
            last_check_time: Optional[datetime] = None,
            check_rate: Optional[timedelta] = None,
            enabled: bool = True,
            seen_item_ids: Optional[List[str]] = None
    ):
        self.subscription_id = subscription_id
        self.chat_id = chat_id
        self.helper = helper
        self.feed_url = feed_url
        self.last_check_time = last_check_time
        self.check_rate = check_rate or isodate.parse_duration("PT1H")
        self.enabled = enabled
        self.seen_item_ids = seen_item_ids or []

    def needs_check(self) -> bool:
        if self.last_check_time is None:
            return True
        return datetime.now() > self.last_check_time + self.check_rate

    @abstractmethod
    async def check_for_new_items(self) -> List["Item"]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def can_handle_link(cls, feed_link: str, helper: SubscriptionHelper) -> bool:
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


class YoutubeDLSubscription(Subscription):
    CHECK_MAX = 10
    VALIDATE_MAX = 2

    async def check_for_new_items(self) -> List["Item"]:
        json_resp = await self.helper.worker.await_task(YoutubeDLDumpJsonTask(self.feed_url, self.CHECK_MAX))
        new_items = []
        for json_line in json_resp.split("\n"):
            json_obj = json.loads(json_line)
            item_id = json_obj["id"]
            if item_id in self.seen_item_ids:
                continue
            video_url = json_obj["webpage_url"]
            if "tiktok.com" in self.feed_url:
                video_url = f"{json_obj['webpage_url']}/video/{json_obj['id']}"
            video_path = await self.helper.download_helper.download_link(video_url)
            item = Item(
                json_obj["id"],
                video_url,
                json_obj["title"],
                video_path,
                is_video=True
            )
            new_items.append(item)
            self.seen_item_ids.append(item.item_id)
        return new_items

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: SubscriptionHelper) -> bool:
        await helper.download_helper.check_yt_dl()
        json_resp = await helper.worker.await_task(YoutubeDLDumpJsonTask(feed_link, 1))
        if not json_resp:
            logger.info(f"Json dump from yt-dl for {feed_link} was empty")
            return False
        try:
            json.loads(json_resp)
            return True
        except JSONDecodeError:
            logger.info(f"Could not parse yt-dl json for feed link: {feed_link}")
            return False


@dataclass
class Item:
    item_id: str
    link: str
    title: Optional[str]
    file_path: Optional[str]
    is_video: bool = False
