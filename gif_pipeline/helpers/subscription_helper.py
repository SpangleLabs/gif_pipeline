import asyncio
import contextlib
import glob
import html
import json
import logging
import os
import re
import shutil
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from json import JSONDecodeError
from typing import List, Optional, TYPE_CHECKING, Type, Dict, Set

import isodate
import asyncpraw
import asyncprawcore
import requests
from prometheus_client import Counter, Gauge

from gif_pipeline import _version
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
        self.sub_classes = []
        if "imgur" in self.api_keys:
            self.sub_classes.append(ImgurSearchSubscription)
        if "reddit" in self.api_keys:
            self.sub_classes.append(RedditSubscription)
        self.sub_classes.append(YoutubeDLSubscription)
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
                        logger.error(
                            f"Failed to post item {item.source_link} from {subscription.feed_url} feed due to: {e}"
                        )
                        await self.send_message(
                            chat,
                            text=f"Failed to post item {item.source_link} from {subscription.feed_url} feed due to: {e}"
                        )
            subscription.last_check_time = datetime.now()
            self.save_subscriptions()

    async def post_item(self, item: "Item", subscription: "Subscription"):
        subscription_posts.labels(subscription_class_name=subscription.__class__.__name__).inc()
        # Get chat
        chat = self.pipeline.chat_by_id(subscription.chat_id)
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
        tags = None
        file_path = await subscription.download_item(item)
        if file_path:
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
            tags.add_tag_value(VideoTags.source, item.source_link)
        # Post item
        await self.send_message(chat, text=caption, video_path=file_path, video_hashes=hash_set, tags=tags)

    async def get_item_hash_set(self, file_path: str, item_id: str, subscription: "Subscription") -> Set[str]:
        # Hash video
        message_decompose_path = f"sandbox/decompose/subs/{subscription.subscription_id}/{item_id}/"
        # Decompose video into images
        os.makedirs(message_decompose_path, exist_ok=True)
        await self.duplicate_helper.decompose_video(file_path, message_decompose_path)
        # Hash the images
        image_files = glob.glob(f"{message_decompose_path}/*.png")
        hash_list = self.duplicate_helper.hash_pool.map(hash_image, image_files)
        hash_set = set(hash_list)
        # Delete the images
        try:
            shutil.rmtree(message_decompose_path)
        except FileNotFoundError:
            pass
        return hash_set

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
            msg += "\n".join(
                f"- {html.escape(sub.feed_url)}"
                for sub in self.subscriptions
                if sub.chat_id == chat.chat_data.chat_id
            )
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
            logger.error(f"Failed to create subscription to {feed_link_out}", exc_info=e)
            return [await self.send_text_reply(
                chat, message,
                f"Could not add subscription to {feed_link_out}. Encountered error: {repr(e)}"
            )]

    def is_priority(self, chat: Chat, message: Message) -> bool:
        split_text = message.text.strip().split()
        if not split_text or split_text[0].lower() not in self.NAMES:
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
        try:
            can_handle_link = await sub_class.can_handle_link(feed_link, helper)
        except:
            continue
        else:
            if not can_handle_link:
                continue
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

    async def download_item(self, item: "Item") -> str:
        video_path = await self.helper.download_helper.download_link(item.download_link)
        return video_path

    def to_data(self) -> SubscriptionData:
        return SubscriptionData(
            self.subscription_id,
            self.feed_url,
            self.chat_id,
            self.last_check_time.isoformat() if self.last_check_time else None,
            isodate.duration_isoformat(self.check_rate),
            self.enabled
        )


class ImgurSearchSubscription(Subscription):
    SEARCH_PATTERN = re.compile(r"imgur.com/(?:t/|search.*\?q=)([^&\n]+)", re.IGNORECASE)

    async def check_for_new_items(self) -> List["Item"]:
        search_term = self.SEARCH_PATTERN.search(self.feed_url)
        api_url = f"https://api.imgur.com/3/gallery/search/?q={search_term.group(1)}"
        api_key = f"Client-ID {self.helper.api_keys['imgur']['client_id']}"
        api_resp = requests.get(api_url, headers={"Authorization": api_key})
        api_data = api_resp.json()
        posts = api_data['data']
        new_items = []
        for post in posts:
            # Handle galleries
            if "images" in post:
                post_images = post["images"]
            else:
                post_images = [post]
            for post_image in post_images:
                if "mp4" not in post_image:
                    continue
                if post_image["id"] in self.seen_item_ids:
                    continue
                new_item = Item(
                    post_image["id"],
                    post_image["mp4"],
                    post["link"],
                    post["title"]
                )
                new_items.append(new_item)
                self.seen_item_ids.append(new_item.item_id)
        return new_items

    async def download_item(self, item: "Item") -> str:
        resp = requests.get(item.download_link)
        file_ext = item.download_link.split(".")[-1]
        file_path = random_sandbox_video_path(file_ext)
        with open(file_path, "wb") as f:
            f.write(resp.content)
        return file_path

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: SubscriptionHelper) -> bool:
        search_term = cls.SEARCH_PATTERN.search(feed_link)
        if search_term:
            return True
        return False


class YoutubeDLSubscription(Subscription):
    CHECK_MAX = 10
    VALIDATE_MAX = 2

    async def check_for_new_items(self) -> List["Item"]:
        json_objs = await self.get_json_dump(self.feed_url, self.helper, self.CHECK_MAX)
        new_items = []
        for json_obj in json_objs:
            item_id = json_obj["id"]
            if item_id in self.seen_item_ids:
                continue
            video_url = json_obj["webpage_url"]
            if "tiktok.com" in self.feed_url:
                video_url = f"{json_obj['webpage_url']}/video/{json_obj['id']}"
            item = Item(
                json_obj["id"],
                video_url,
                video_url,
                json_obj["title"]
            )
            new_items.append(item)
            self.seen_item_ids.append(item.item_id)
        return new_items

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: SubscriptionHelper) -> bool:
        await helper.download_helper.check_yt_dl()
        try:
            json_resp = await cls.get_json_dump(feed_link, helper, 1)
            if not json_resp:
                logger.info(f"Json dump from yt-dl for {feed_link} was empty")
                return False
            return True
        except JSONDecodeError:
            logger.info(f"Could not parse yt-dl json for feed link: {feed_link}")
            return False

    @classmethod
    async def get_json_dump(
            cls,
            feed_link: str,
            helper: SubscriptionHelper,
            feed_items: Optional[int] = None
    ) -> List[Dict]:
        feed_items = feed_items or cls.CHECK_MAX
        attempts = 5
        sleep_wait = 3
        attempt = 1
        while True:
            try:
                json_resp = await helper.worker.await_task(YoutubeDLDumpJsonTask(feed_link, feed_items))
                return [
                    json.loads(line)
                    for line in json_resp.split("\n")
                ]
            except Exception as e:
                attempt += 1
                logger.warning("Youtube dl dump json task failed: ", exc_info=e)
                await asyncio.sleep(sleep_wait)
                if attempt > attempts:
                    raise e


@contextlib.asynccontextmanager
async def reddit_client(helper: SubscriptionHelper) -> asyncpraw.Reddit:
    username = helper.api_keys['reddit']['owner_username']
    user_agent = f"line:gif_pipeline:v{_version.__VERSION__} (by u/{username})"
    reddit = asyncpraw.Reddit(
        client_id=helper.api_keys["reddit"]["client_id"],
        client_secret=helper.api_keys["reddit"]["client_secret"],
        user_agent=user_agent
    )
    yield reddit
    await reddit.close()


class RedditSubscription(Subscription):
    SEARCH_PATTERN = re.compile(r"reddit.com/r/(\S+)", re.IGNORECASE)
    LIMIT = 10

    async def check_for_new_items(self) -> List["Item"]:
        subreddit_name = self.SEARCH_PATTERN.search(self.feed_url)
        new_items = []
        async with reddit_client(self.helper) as reddit:
            subreddit = await reddit.subreddit(subreddit_name.group(1))
            async for submission in subreddit.new(limit=self.LIMIT):
                if submission.id in self.seen_item_ids:
                    continue
                link = f"https://reddit.com{submission.permalink}"
                new_item = Item(
                    submission.id,
                    link,
                    link,
                    submission.title
                )
                new_items.append(new_item)
                self.seen_item_ids.append(new_item.item_id)
        return new_items

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: SubscriptionHelper) -> bool:
        search_term = cls.SEARCH_PATTERN.search(feed_link)
        if search_term:
            try:
                async with reddit_client(helper) as reddit:
                    async for result in reddit.subreddits.search_by_name(search_term.group(1), exact=True):
                        return True
            except asyncprawcore.NotFound:
                return False
        return False

    async def download_item(self, item: "Item") -> str:
        video_path = await self.helper.download_helper.download_link(item.download_link)
        return video_path


@dataclass
class Item:
    item_id: str
    download_link: str
    source_link: str
    title: Optional[str]
