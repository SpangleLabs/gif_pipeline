import re
from typing import TYPE_CHECKING, List

import bleach
import feedparser

from gif_pipeline.helpers.subscriptions.subscription import Item, Subscription

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper


class InstagramSubscription(Subscription):
    SEARCH_PATTERN = re.compile(r"instagram.com/([^\\&#\n]+)", re.IGNORECASE)

    @property
    def bibliogram_url(self) -> str:
        return self.helper.api_keys["instagram"]["bibliogram_url"]

    def link_to_insta_link(self, link: str) -> str:
        return link.replace(self.bibliogram_url, "https://www.instagram.com")

    async def check_for_new_items(self) -> List["Item"]:
        search_term = self.SEARCH_PATTERN.search(self.feed_url)
        rss_link = f"{self.bibliogram_url}/u/{search_term.group(1)}/rss.xml"
        new_items = []
        feed = feedparser.parse(rss_link)
        for entry in feed.entries:
            entry_id = self.link_to_insta_link(entry.id)
            entry_link = self.link_to_insta_link(entry.link)
            if entry_id in self.seen_item_ids:
                continue
            new_item = Item(
                entry_id,
                entry_link,
                entry_link,
                bleach.clean(entry.title, tags=[], strip=True)
            )
            new_items.append(new_item)
            self.seen_item_ids.append(new_item.item_id)
        return new_items

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
        search_term = cls.SEARCH_PATTERN.search(feed_link)
        bibliogram_url = helper.api_keys.get("instagram", {}).get("bibliogram_url")
        if not search_term or not bibliogram_url:
            return False
        rss_link = f"{bibliogram_url}/u/{search_term.group(1)}/rss.xml"
        feed = feedparser.parse(rss_link)
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
