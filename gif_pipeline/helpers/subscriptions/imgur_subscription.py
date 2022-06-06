import re
from typing import TYPE_CHECKING, List

import requests

from gif_pipeline.helpers.helpers import random_sandbox_video_path
from gif_pipeline.helpers.subscriptions.subscription import Item, Subscription

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper


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
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
        search_term = cls.SEARCH_PATTERN.search(feed_link)
        if search_term:
            return True
        return False
