import re
from typing import List, TYPE_CHECKING, Optional

from gif_pipeline.helpers.download_helper import DownloadHelper
from gif_pipeline.helpers.helpers import random_sandbox_video_path
from gif_pipeline.helpers.subscriptions.subscription import Subscription, Item

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper
    from gif_pipeline.message import MessageData


def message_to_items(msg: MessageData, handle: str) -> List[Item]:
    raw_msg_link = f"https://t.me/c/{msg.chat_id}/{msg.message_id}"
    msg_link = raw_msg_link
    try:
        int(handle)
    except ValueError:
        msg_link = f"https://t.me/{handle}/{msg.message_id}"
    if msg.has_video:
        return [Item(
            str(msg.message_id),
            raw_msg_link,
            msg_link,
            msg.text
        )]
    links = [match.group(0) for match in re.finditer(DownloadHelper.LINK_REGEX, msg.text, re.IGNORECASE)]
    if not links:
        return []
    items = []
    for link in links:
        if any(url in link for url in ["youtu", "twitter.com", "imgur.com"]):
            items.append(Item(
                str(msg.message_id),
                link,
                msg_link,
                msg.text
            ))
    return items


class TelegramSubscription(Subscription):
    SEARCH_PATTERN = re.compile(r"t.me/(?:c/)?([^\\&#\n/]+)", re.IGNORECASE)

    async def check_for_new_items(self) -> List["Item"]:
        search_term = self.SEARCH_PATTERN.search(self.feed_url)
        telegram_handle = search_term.group(1)
        max_msg_id = max([int(i) for i in self.seen_item_ids])
        new_items = []
        async for msg in self.helper.client.list_messages_since(telegram_handle, min_id=max_msg_id):
            items = message_to_items(msg, telegram_handle)
            new_items += items
            self.seen_item_ids.append(str(msg.message_id))
        self.seen_item_ids = [max([int(i) for i in self.seen_item_ids])]
        return new_items

    async def download_item(self, item: "Item") -> str:
        if item.download_link.startswith("https://t.me/"):
            link_split = item.download_link.strip("/").split("/")
            msg_id = int(link_split[-1])
            chat_id = int(link_split[-2])
            output_path = random_sandbox_video_path("")
            await self.helper.client.download_media(chat_id, msg_id, output_path)
            return output_path
        else:
            return await super().download_item(item)

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
        search_term = cls.SEARCH_PATTERN.search(feed_link)
        telegram_handle = search_term.group(1)
        async for msg in helper.client.list_messages_since(telegram_handle, limit=10):
            message_to_items(msg, telegram_handle)
        return True

