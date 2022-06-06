import re
from typing import TYPE_CHECKING, List

import bleach
import feedparser

from gif_pipeline.helpers.subscriptions.subscription import Item, Subscription

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper


class TwitterSubscription(Subscription):
    SEARCH_PATTERN = re.compile(r"twitter.com/([^\\&#\n]+(?:/media|/with_replies|))", re.IGNORECASE)

    @property
    def nitter_url(self) -> str:
        return self.helper.api_keys["twitter"]["nitter_url"]

    def link_to_twitter_link(self, link: str) -> str:
        return link.replace(self.nitter_url, "https://twitter.com")

    async def check_for_new_items(self) -> List["Item"]:
        search_term = self.SEARCH_PATTERN.search(self.feed_url)
        rss_link = f"{self.nitter_url}/{search_term.group(1)}/rss"
        new_items = []
        feed = feedparser.parse(rss_link)
        for entry in feed.entries:
            entry_id = self.link_to_twitter_link(entry.id)
            entry_link = self.link_to_twitter_link(entry.link)
            if entry_id in self.seen_item_ids:
                continue
            new_item = Item(entry_id, entry_link, entry_link, bleach.clean(entry.title, tags=[], strip=True))
            new_items.append(new_item)
            self.seen_item_ids.append(new_item.item_id)
        return new_items

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
        search_term = cls.SEARCH_PATTERN.search(feed_link)
        nitter_url = helper.api_keys.get("twitter", {}).get("nitter_url")
        if not search_term or not nitter_url:
            return False
        rss_link = f"{nitter_url}/{search_term.group(1)}/rss"
        feed = feedparser.parse(rss_link)
        if not feed.entries:
            return False
        for entry in feed.entries:
            Item(entry.id, entry.link, entry.link, bleach.clean(entry.title, tags=[], strip=True))
        return True
