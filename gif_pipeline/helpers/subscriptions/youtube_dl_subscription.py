import asyncio
import json
import logging
from json import JSONDecodeError
from typing import List, Optional, Dict, TYPE_CHECKING

from gif_pipeline.helpers.subscriptions.subscription import Subscription, Item
from gif_pipeline.tasks.youtube_dl_task import YoutubeDLDumpJsonTask

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper


logger = logging.getLogger(__name__)


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
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
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
            helper: "SubscriptionHelper",
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
