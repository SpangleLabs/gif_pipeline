import logging
import re
from typing import TYPE_CHECKING, List, Optional, Union

from gif_pipeline.helpers.download_helper import DownloadHelper
from gif_pipeline.helpers.helpers import random_sandbox_video_path
from gif_pipeline.helpers.subscriptions.subscription import Item, Subscription

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper
    from gif_pipeline.message import MessageData


logger = logging.getLogger(__name__)


def message_to_items(msg: "MessageData", handle: Union[str, int]) -> List[Item]:
    chat_id = str(msg.chat_id)
    if chat_id.startswith("-100"):
        chat_id = chat_id[4:]
    raw_msg_link = f"https://t.me/c/{msg.chat_id}/{msg.message_id}"
    msg_link = f"https://t.me/c/{chat_id}/{msg.message_id}"
    try:
        int(handle)
    except ValueError:
        msg_link = f"https://t.me/{handle}/{msg.message_id}"
    if msg.has_video:
        return [Item(str(msg.message_id), raw_msg_link, msg_link, msg.text)]
    if not msg.text:
        return []
    links = [match.group(0) for match in re.finditer(DownloadHelper.LINK_REGEX, msg.text, re.IGNORECASE)]
    if not links:
        return []
    items = []
    for link in links:
        if any(url in link for url in ["youtu", "twitter.com", "imgur.com"]):
            items.append(Item(str(msg.message_id), link, msg_link, msg.text, _tag_source=link))
    return items


class TelegramSubscription(Subscription):
    SEARCH_PATTERN = re.compile(r"t.me/(?:c/)?([^\\&#\n/]+)", re.IGNORECASE)

    async def check_for_new_items(self) -> List["Item"]:
        telegram_handle = self.parse_feed_url(self.feed_url)
        if telegram_handle is None:
            raise ValueError("Feed is not a valid telegram handle?")
        if self.seen_item_ids:
            max_msg_id = max([int(i) for i in self.seen_item_ids])
            limit = None
        else:
            max_msg_id = 0
            limit = 10
        new_items = []
        async for msg in self.helper.client.list_messages_since(telegram_handle, min_id=max_msg_id, limit=limit):
            items = message_to_items(msg, telegram_handle)
            new_items += items
            self.seen_item_ids.append(str(msg.message_id))
        self.seen_item_ids = [max([int(i) for i in self.seen_item_ids])]
        return new_items

    async def download_item(self, item: "Item") -> Optional[str]:
        if item.download_link.startswith("https://t.me/"):
            link_split = item.download_link.strip("/").split("/")
            msg_id = int(link_split[-1])
            chat_id = int(link_split[-2])
            output_path = random_sandbox_video_path()
            return await self.helper.client.download_media(chat_id, msg_id, output_path)
        else:
            try:
                return await super().download_item(item)
            except Exception as e:
                logger.warning("Telegram subscription failed to download link: %s", item.download_link, exc_info=e)
                return None

    @classmethod
    def parse_feed_url(cls, feed_link: str) -> Optional[Union[int, str]]:
        search_term = cls.SEARCH_PATTERN.search(feed_link)
        if search_term is None:
            return None
        telegram_handle = search_term.group(1)
        try:
            telegram_handle = int(telegram_handle)
        except ValueError:
            pass
        return telegram_handle

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
        telegram_handle = cls.parse_feed_url(feed_link)
        if telegram_handle is None:
            return False
        async for msg in helper.client.list_messages_since(telegram_handle, limit=10):
            message_to_items(msg, telegram_handle)
        return True
