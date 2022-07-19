import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, List, TYPE_CHECKING, Type

import isodate

from gif_pipeline.database import SubscriptionData

if TYPE_CHECKING:
    from gif_pipeline.helpers.subscription_helper import SubscriptionHelper

logger = logging.getLogger(__name__)


class Subscription(ABC):

    def __init__(
            self,
            feed_url: str,
            chat_id: int,
            helper: "SubscriptionHelper",
            *,
            subscription_id: int = None,
            last_check_time: Optional[datetime] = None,
            check_rate: Optional[timedelta] = None,
            enabled: bool = True,
            seen_item_ids: Optional[List[str]] = None
    ):
        self.subscription_id = subscription_id
        self.chat_id = chat_id
        self.helper = helper
        self.feed_url = feed_url
        self.last_check_time = last_check_time
        self.check_rate = check_rate or isodate.parse_duration("PT1H")
        self.enabled = enabled
        self.seen_item_ids = seen_item_ids or []

    def needs_check(self) -> bool:
        if self.last_check_time is None:
            return True
        return datetime.now() > self.last_check_time + self.check_rate

    @abstractmethod
    async def check_for_new_items(self) -> List["Item"]:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def can_handle_link(cls, feed_link: str, helper: "SubscriptionHelper") -> bool:
        pass

    async def download_item(self, item: "Item") -> Optional[str]:
        video_path = await self.helper.download_helper.download_link(item.download_link)
        return video_path

    def to_data(self) -> SubscriptionData:
        return SubscriptionData(
            self.subscription_id,
            self.feed_url,
            self.chat_id,
            self.last_check_time.isoformat() if self.last_check_time else None,
            isodate.duration_isoformat(self.check_rate),
            self.enabled
        )

    @property
    def subscription_type(self) -> Type["Subscription"]:
        return type(self)

    def is_subscription_type(self, cls: Type["Subscription"]):
        return isinstance(self, cls)


@dataclass
class Item:
    item_id: str
    download_link: str
    source_link: str
    title: Optional[str]
    _tag_source: Optional[str] = None

    @property
    def tag_source_link(self) -> str:
        if self._tag_source:
            return self._tag_source
        return self.source_link


async def create_sub_for_link(
        feed_link: str,
        chat_id: int,
        helper: "SubscriptionHelper",
        sub_classes: List[Type["Subscription"]],
        *,
        subscription_id: int = None,
        last_check_time: Optional[datetime] = None,
        check_rate: Optional[timedelta] = None,
        enabled: bool = True,
        seen_item_ids: Optional[List[str]] = None
) -> Optional["Subscription"]:
    for sub_class in sub_classes:
        try:
            can_handle_link = await sub_class.can_handle_link(feed_link, helper)
            logger.debug(
                "Subscription class %s has checked feed %s, can handle link: %s",
                sub_class.__name__,
                feed_link,
                can_handle_link
            )
        except Exception as e:
            logger.warning(
                "Sub class %s raised exception while trying to handle link: %s",
                sub_class.__name__,
                feed_link,
                exc_info=e
            )
            continue
        else:
            if not can_handle_link:
                continue
            logger.debug("Creating subscription for %s as %s", feed_link, sub_class.__name__)
            return sub_class(
                feed_link,
                chat_id,
                helper,
                subscription_id=subscription_id,
                last_check_time=last_check_time,
                check_rate=check_rate,
                enabled=enabled,
                seen_item_ids=seen_item_ids
            )
    return None
