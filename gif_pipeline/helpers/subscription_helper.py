import asyncio
import html
import logging
from datetime import datetime
from typing import List, Optional, TYPE_CHECKING, Dict, Set, Type

import isodate
from PIL import Image
from prometheus_client import Counter, Gauge
from telethon import Button

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, random_sandbox_video_path
from gif_pipeline.helpers.subscriptions.imgur_subscription import ImgurSearchSubscription
from gif_pipeline.helpers.subscriptions.instagram_subscription import InstagramSubscription
from gif_pipeline.helpers.subscriptions.reddit_subscription import RedditSubscription
from gif_pipeline.helpers.subscriptions.rss_subscription import RSSSubscription
from gif_pipeline.helpers.subscriptions.subscription import Subscription, Item, create_sub_for_link
from gif_pipeline.helpers.subscriptions.telegram_subscription import TelegramSubscription
from gif_pipeline.helpers.subscriptions.twitter_subscription import TwitterSubscription
from gif_pipeline.helpers.subscriptions.unitialised_subscription import UninitialisedSubscription
from gif_pipeline.helpers.subscriptions.youtube_dl_subscription import YoutubeDLSubscription
from gif_pipeline.helpers.video_helper import video_to_video
from gif_pipeline.message import Message
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
    labelnames=["subscription_class_name", "chat_title"]
)

subscription_posts = Counter(
    "gif_pipeline_subscription_helper_post_count_total",
    "Total number of posts sent by the subscription helper",
    labelnames=["subscription_class_name", "chat_title"]
)


def is_static_image(file_path: str) -> bool:
    file_ext = file_path.split(".")[-1]
    if file_ext in ["jpg", "jpeg"]:
        return True
    if file_ext in ["gif", "png"]:
        with Image.open(file_path) as img:
            # is_animated attribute might not exist, if file is a jpg named ".png"
            return getattr(img, "is_animated", False)
    return False


class SubscriptionException(Exception):
    pass


class SubscriptionHelper(Helper):
    CHECK_DELAY = 60
    NAMES = ["subscribe", "sub", "subs", "subscription", "subscriptions"]

    def __init__(
            self,
            database: "Database",
            client: "TelegramClient",
            worker: "TaskWorker",
            pipeline: "Pipeline",
            duplicate_helper: "DuplicateHelper",
            download_helper: "DownloadHelper",
            api_keys: Dict[str, Dict[str, str]]
    ):
        super().__init__(database, client, worker)
        self.pipeline = pipeline
        self.duplicate_helper = duplicate_helper
        self.download_helper = download_helper
        self.api_keys = api_keys
        self.subscriptions: List[Subscription] = []
        self.sub_classes: List[Type[Subscription]] = []
        if "imgur" in self.api_keys:
            self.sub_classes.append(ImgurSearchSubscription)
        if "reddit" in self.api_keys:
            self.sub_classes.append(RedditSubscription)
        if "twitter" in self.api_keys and "nitter_url" in self.api_keys["twitter"]:
            self.sub_classes.append(TwitterSubscription)
        if "instagram" in self.api_keys:
            self.sub_classes.append(InstagramSubscription)
        self.sub_classes.append(RSSSubscription)
        self.sub_classes.append(TelegramSubscription)
        self.sub_classes.append(YoutubeDLSubscription)  # This subscription type will try anything. Always put it last.
        # Initialise counters
        all_classes = self.sub_classes + [UninitialisedSubscription]
        for sub_class in all_classes:
            for workshop in self.pipeline.workshops:
                subscription_posts.labels(
                    subscription_class_name=sub_class.__name__,
                    chat_title=workshop.chat_data.title
                )
                subscription_count.labels(
                    subscription_class_name=sub_class.__name__,
                    chat_title=workshop.chat_data.title
                ).set_function(
                    lambda cls=sub_class, chat_id=workshop.chat_data.chat_id: len([
                        s for s in self.subscriptions
                        if s.is_subscription_type(cls) and s.chat_id == chat_id
                    ])
                )

    async def initialise(self) -> None:
        logger.debug("Loading subscriptions")
        self.subscriptions = await load_subs_from_database(self.database, self)
        logger.debug("Loaded all subscriptions")
        asyncio.get_event_loop().create_task(self.sub_checker())
        logger.debug("Started subscription checker task")

    async def sub_checker(self) -> None:
        while True:
            try:
                await self.check_subscriptions()
            except Exception as e:
                logger.error("Failed to check subscriptions, due to exception: ", exc_info=e)
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
                logger.warning("Subscription to %s failed due to:", subscription.feed_url, exc_info=e)
                # Just increment a counter please
                subscription.failures += 1
                self.save_subscription(subscription)
            else:
                for item in new_items:
                    try:
                        await self.post_item(item, subscription)
                    except Exception as e:
                        logger.error(
                            "Failed to post item %s from %s feed due to:",
                            item.source_link,
                            subscription.feed_url,
                            exc_info=e
                        )
                        feed_url = subscription.feed_url
                        await self.send_message(
                            chat,
                            text=f"Failed to post item {item.source_link} from {feed_url} feed due to: {e}",
                            buttons=[[Button.inline("Delete error", "delete_me")]]
                        )
            subscription.failures = 0
            subscription.last_check_time = datetime.now()
            if subscription.feed_url in [sub.feed_url for sub in self.subscriptions[:]]:
                self.save_subscription(subscription)

    async def post_item(self, item: "Item", subscription: "Subscription") -> None:
        # Get chat
        chat = self.pipeline.chat_by_id(subscription.chat_id)
        # Metrics
        subscription_posts.labels(
            subscription_class_name=subscription.subscription_type.__name__,
            chat_title=chat.chat_data.title
        ).inc()
        # Construct caption
        title = "-"
        if item.title:
            title = html.escape(item.title)
        caption = (
            f"<a href=\"{item.source_link}\">{title}</a>\n\n"
            f"Feed: {html.escape(subscription.feed_url)}"
        )
        # If item has video and chat has duplicate detection
        hash_set = None
        file_path = await subscription.download_item(item)
        # Only post videos
        if not file_path or is_static_image(file_path):
            return
        # Convert to video
        output_path = random_sandbox_video_path()
        tasks = video_to_video(file_path, output_path)
        for task in tasks:
            await self.worker.await_task(task)
        file_path = output_path
        # Check duplicate warnings
        if chat.config.duplicate_detection:
            hash_set = await self.get_item_hash_set(file_path, item.item_id, subscription)
            warnings = await self.check_item_duplicate(hash_set)
            if warnings:
                caption += "\n\n" + "\n".join(warnings)
        # Build tags
        tags = VideoTags()
        tags.add_tag_value(VideoTags.source, item.tag_source_link)
        # Post item
        await self.send_message(chat, text=caption, video_path=file_path, video_hashes=hash_set, tags=tags)

    async def get_item_hash_set(self, file_path: str, item_id: str, subscription: "Subscription") -> Set[str]:
        # Hash video
        message_decompose_path = f"sandbox/decompose/subs/{subscription.subscription_id}/{item_id}/"
        return await self.duplicate_helper.create_message_hashes_in_dir(file_path, message_decompose_path)

    async def check_item_duplicate(self, hash_set: Set[str]) -> List[str]:
        # Find duplicates
        has_blank_frame = self.duplicate_helper.blank_frame_hash in hash_set
        if has_blank_frame:
            hash_set.remove(self.duplicate_helper.blank_frame_hash)
        matching_messages = set(self.database.get_messages_for_hashes(hash_set))
        warnings = self.duplicate_helper.get_duplicate_warnings(matching_messages, has_blank_frame)
        return warnings

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        split_text = message.text.split()
        if not split_text or split_text[0].lower() not in self.NAMES:
            return None
        self.usage_counter.inc()
        if len(split_text) < 2:
            return [await self.send_text_reply(chat, message, "Please specify a feed link to subscribe to.")]
        if split_text[1] in ["list"]:
            msg = "List of subscriptions currently posting to this chat are:\n"
            lines = []
            for sub in self.subscriptions:
                if sub.chat_id != chat.chat_data.chat_id:
                    continue
                line = f"- {html.escape(sub.feed_url)}"
                if sub.failures > 0:
                    line += f" (Failed last {sub.failures} checks)"
                lines.append(line)
            msg += "\n".join(lines)
            return [await self.send_text_reply(chat, message, msg)]
        if split_text[1] in ["remove", "delete"]:
            feed_link = split_text[2]
            feed_link_out = html.escape(feed_link)
            matching_sub = next((sub for sub in self.subscriptions if sub.feed_url == feed_link), None)
            if not matching_sub:
                return [await self.send_text_reply(
                    chat, message, f"Cannot remove subscription, as none match the feed link: {feed_link_out}"
                )]
            self.subscriptions.remove(matching_sub)
            self.database.remove_subscription(matching_sub.to_data())
            self.save_subscriptions()
            return [await self.send_text_reply(chat, message, f"Removed subscription to {feed_link_out}")]
        feed_link = split_text[1]
        feed_link_out = html.escape(feed_link)
        # TODO: Allow specifying extra arguments?
        try:
            async with self.progress_message(chat, message, "Creating subscription"):
                subscription = await create_sub_for_link(feed_link, chat.chat_data.chat_id, self, self.sub_classes)
                if subscription is None:
                    return [await self.send_text_reply(
                        chat, message, f"No subscription handler was able to handle {feed_link_out}"
                    )]
                await subscription.check_for_new_items()
                self.subscriptions.append(subscription)
                self.save_subscriptions()
                return [await self.send_text_reply(chat, message, f"Added subscription for {feed_link_out}")]
        except Exception as e:
            logger.error("Failed to create subscription to %s", feed_link_out, exc_info=e)
            return [await self.send_text_reply(
                chat, message,
                f"Could not add subscription to {feed_link_out}. Encountered error: {repr(e)}"
            )]

    def is_priority(self, chat: Chat, message: Message) -> bool:
        split_text = message.text.strip().split()
        if not split_text or split_text[0].lower() not in self.NAMES:
            return False
        return True

    def save_subscriptions(self) -> None:
        for subscription in self.subscriptions:
            self.save_subscription(subscription)

    def save_subscription(self, subscription: Subscription) -> None:
        new_sub = subscription.subscription_id is None
        saved_data = self.database.save_subscription(subscription.to_data(), subscription.seen_item_ids)
        if new_sub:
            subscription.subscription_id = saved_data.subscription_id


async def load_subs_from_database(database: "Database", helper: SubscriptionHelper) -> List["Subscription"]:
    sub_data = database.list_subscriptions()
    subscriptions = []
    for sub_entry in sub_data:
        seen_items = database.list_item_ids_for_subscription(sub_entry)
        logger.debug("Loading subscription %s with %s seen items", sub_entry.feed_link, len(seen_items))
        subscription = await create_sub_for_link(
            sub_entry.feed_link,
            sub_entry.chat_id,
            helper,
            [UninitialisedSubscription],
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
