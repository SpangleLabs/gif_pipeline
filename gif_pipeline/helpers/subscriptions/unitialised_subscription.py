import logging
from typing import List, TYPE_CHECKING, Type

from gif_pipeline.helpers.subscriptions.subscription import Subscription, Item, create_sub_for_link

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper


logger = logging.getLogger(__name__)


class UninitialisedSubscription(Subscription):
    """
    This is a subscription class for subscriptions which could not be handled when the gif pipeline was started up.
    Usually this happens when a subscription handler can no longer handle a subscription, that it could when the
    subscription was created. The most likely situation is something that yt-dlp could handle, but has now changed, and
    yt-dlp cannot yet handle it.
    """
    CHECK_MAX = 10
    VALIDATE_MAX = 2

    def __init__(self, feed_url: str, chat_id: int, helper: "SubscriptionHelper", **kwargs):
        super().__init__(feed_url, chat_id, helper, **kwargs)
        self.found_sub = None

    async def check_for_new_items(self) -> List["Item"]:
        if self.found_sub is not None:
            return await self.found_sub.check_for_new_items()
        # Try and load in various
        classes = self.helper.sub_classes
        self.found_sub = await create_sub_for_link(
            self.feed_url,
            self.chat_id,
            self.helper,
            classes,
            subscription_id=self.subscription_id,
            last_check_time=self.last_check_time,
            check_rate=self.check_rate,
            enabled=self.enabled,
            seen_item_ids=self.seen_item_ids
        )
        if self.found_sub is None:
            raise ValueError(f"Could not initialise subscription: {self.feed_url}")
        return await self.found_sub.check_for_new_items()

    @classmethod
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
        return True

    async def download_item(self, item: "Item") -> str:
        if self.found_sub is not None:
            return await self.found_sub.download_item(item)
        raise ValueError("Could not download new item, as this subscription is uninitialised")
    
    @property
    def subscription_type(self) -> Type["Subscription"]:
        if self.found_sub is None:
            return type(self)
        return type(self.found_sub)

    def is_subscription_type(self, cls: Type["Subscription"]):
        if self.found_sub is None:
            return isinstance(self, cls)
        return isinstance(self.found_sub, cls)
