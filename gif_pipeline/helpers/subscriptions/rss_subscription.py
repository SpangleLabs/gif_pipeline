from typing import List, TYPE_CHECKING

import bleach
import feedparser

from gif_pipeline.helpers.subscriptions.subscription import Subscription, Item

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper


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
            feed = feedparser.parse(feed_link)
            for entry in feed.entries:
                Item(
                    entry.id,
                    entry.link,
                    entry.link,
                    bleach.clean(entry.title, tags=[], strip=True)
                )
            return True
        except:
            return False
