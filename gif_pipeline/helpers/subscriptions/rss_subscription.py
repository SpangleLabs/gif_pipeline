import logging
from typing import TYPE_CHECKING, List

import bleach
import feedparser
import requests

from gif_pipeline.helpers.subscriptions.subscription import Item, Subscription

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper


logger = logging.getLogger(__name__)


class RSSSubscription(Subscription):

    async def check_for_new_items(self) -> List["Item"]:
        new_items = []
        feed = feedparser.parse(self.feed_url)
        for entry in feed.entries:
            if entry.id in self.seen_item_ids:
                continue
            new_item = Item(
                entry.id,
                entry.link,
                entry.link,
                bleach.clean(entry.title, tags=[], strip=True)
            )
            new_items.append(new_item)
            self.seen_item_ids.append(new_item.item_id)
        return new_items

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
        try:
            feed_data = requests.get(feed_link, timeout=10).text
            feed = feedparser.parse(feed_data)
            if not feed.entries:
                return False
            for entry in feed.entries:
                Item(
                    entry.id,
                    entry.link,
                    entry.link,
                    bleach.clean(entry.title, tags=[], strip=True)
                )
            return True
        except Exception as e:
            logger.info("RSS Parser could not read feed %s", feed_link, exc_info=e)
            return False
