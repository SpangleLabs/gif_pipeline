import contextlib
import re
from typing import TYPE_CHECKING, List

import asyncpraw
import asyncprawcore

from gif_pipeline import _version
from gif_pipeline.helpers.subscriptions.subscription import Item, Subscription

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper


@contextlib.asynccontextmanager
async def reddit_client(helper: "SubscriptionHelper") -> asyncpraw.Reddit:
    username = helper.api_keys["reddit"]["owner_username"]
    user_agent = f"line:gif_pipeline:v{_version.__VERSION__} (by u/{username})"
    reddit = asyncpraw.Reddit(
        client_id=helper.api_keys["reddit"]["client_id"],
        client_secret=helper.api_keys["reddit"]["client_secret"],
        user_agent=user_agent,
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
                if submission.is_self:
                    continue
                link = f"https://reddit.com{submission.permalink}"
                new_item = Item(submission.id, link, link, submission.title)
                new_items.append(new_item)
                self.seen_item_ids.append(new_item.item_id)
        return new_items

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
        search_term = cls.SEARCH_PATTERN.search(feed_link)
        if search_term:
            try:
                async with reddit_client(helper) as reddit:
                    async for _ in reddit.subreddits.search_by_name(search_term.group(1), exact=True):
                        return True
            except asyncprawcore.NotFound:
                return False
        return False
