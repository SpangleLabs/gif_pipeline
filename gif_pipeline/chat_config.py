from abc import ABC, abstractmethod
from datetime import timedelta
from enum import Enum
from typing import Union, Dict, Any, Optional

import isodate

from gif_pipeline.text_formatter import TextFormatter


class TagType(Enum):
    NORMAL = "normal"  # Store a list of values for this tag
    SINGLE = "single"  # Store a single value for this tag
    TEXT = "text"  # Store a text string for this tag, do not list the other values
    GNOSTIC = "gnostic"  # Store a list of positive and negative values for this tag


class TagConfig:
    def __init__(self, tag_type: TagType):
        self.type = tag_type

    @staticmethod
    def from_json(json_dict: Dict[str, Any]) -> 'TagConfig':
        tag_type_str = json_dict.get("type", "normal")
        try:
            tag_type = TagType[tag_type_str.upper()]
        except KeyError as e:
            raise KeyError(f"Invalid tag type, \"{tag_type_str}\": {e}")
        return TagConfig(tag_type)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(type={self.type})"


class ScheduleOrder(Enum):
    RANDOM = "random"
    OLDEST_FIRST = "oldest_first"
    NEWEST_FIRST = "newest_first"


class ScheduleConfig:
    def __init__(
            self,
            min_time: timedelta,
            *,
            max_time: timedelta = None,
            order: ScheduleOrder = None,
            target_length: timedelta = None,
            schedule_variability_percent: int = 15,
    ):
        self.min_time = min_time
        self.max_time = max_time
        self.order = order or ScheduleOrder.RANDOM
        self.target_length = target_length
        self.schedule_variability_percent = schedule_variability_percent

    @property
    def avg_time(self) -> timedelta:
        if self.max_time is None:
            return self.min_time
        return (self.max_time + self.min_time) / 2

    @staticmethod
    def from_json(json_dict: Dict[str, Any]) -> 'ScheduleConfig':
        min_time_str = json_dict["min_time"]
        max_time_str = json_dict.get("max_time")
        order_str = json_dict.get("order")
        target_length_str = json_dict.get("target_queue_length")
        schedule_variability = json_dict.get("schedule_variability_percent", 15)
        min_time = isodate.parse_duration(min_time_str)
        max_time = None
        if max_time_str:
            max_time = isodate.parse_duration(max_time_str)
        order = None
        if order_str:
            try:
                order = ScheduleOrder[order_str.upper()]
            except KeyError as e:
                raise KeyError(f"Invalid schedule order, \"{order_str}\": {e}")
        target_length = None
        if target_length_str:
            target_length = isodate.parse_duration(target_length_str)
        return ScheduleConfig(
            min_time=min_time,
            max_time=max_time,
            order=order,
            target_length=target_length,
            schedule_variability_percent=schedule_variability,
        )


class TwitterAccountConfig:

    def __init__(self, access_token: str, access_secret: str):
        self.access_token = access_token
        self.access_secret = access_secret

    @classmethod
    def from_json(cls, json_dict: Dict) -> "TwitterAccountConfig":
        return cls(
            json_dict["access_token"],
            json_dict["access_secret"]
        )


class TwitterReplyConfig:

    def __init__(
        self,
        text: str,
        reply: Optional["TwitterReplyConfig"] = None,
        account: Optional["TwitterAccountConfig"] = None,
    ):
        self.text_format = TextFormatter(text)
        self.reply = reply
        self.account = account

    @classmethod
    def from_json(cls, json_dict: Dict) -> "TwitterReplyConfig":
        reply = None
        if "reply" in json_dict:
            reply = TwitterReplyConfig.from_json(json_dict["reply"])
        account = None
        if "account" in json_dict:
            account = TwitterAccountConfig.from_json(json_dict["account"])
        return cls(
            json_dict["text"],
            reply,
            account
        )


class TwitterConfig:

    def __init__(self, account: TwitterAccountConfig, text: str, reply: Optional[TwitterReplyConfig] = None):
        self.account = account
        self.text_format = TextFormatter(text)
        self.reply = reply

    @classmethod
    def from_json(cls, json_dict: Dict) -> "TwitterConfig":
        reply = None
        if "reply" in json_dict:
            reply = TwitterReplyConfig.from_json(json_dict["reply"])
        return cls(
            TwitterAccountConfig.from_json(json_dict["account"]),
            json_dict.get("text", ""),
            reply
        )


class WebsiteConfig:

    def __init__(self, enabled: bool, publicly_listed: bool) -> None:
        self.enabled = enabled
        self.publicly_listed = publicly_listed

    @classmethod
    def from_json(cls, json_dict: Optional[Dict]) -> "WebsiteConfig":
        if json_dict is None:
            return cls(False, False)
        return cls(
            json_dict.get("enabled", True),
            json_dict.get("publicly_listed", False),
        )


class ChatConfig(ABC):
    def __init__(
            self,
            handle: Union[str, int],
            *,
            duplicate_detection: bool = True,
            default_destination: Optional[Union[str, int]] = None,
    ):
        self.handle = handle
        self.duplicate_detection = duplicate_detection
        self.read_only = False
        self.twitter_config: Optional[TwitterConfig] = None
        self.caption_format = TextFormatter("")
        self.default_dest_handle = default_destination

    @staticmethod
    @abstractmethod
    def from_json(json_dict: Dict[str, Any]) -> 'ChatConfig':
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(handle={self.handle})"


class ChannelConfig(ChatConfig):

    def __init__(
            self,
            handle: Union[str, int],
            *,
            queue: 'QueueConfig' = None,
            read_only: bool = False,
            send_folder: Optional[str] = None,
            note_time: bool = False,
            tags: Optional[Dict[str, TagConfig]] = None,
            twitter_config: Optional[TwitterConfig] = None,
            caption: str = "",
            website_config: WebsiteConfig = None,
    ):
        super().__init__(handle)
        self.queue = queue
        self.read_only = read_only
        self.send_folder = send_folder
        self.note_time = note_time
        self.tags = tags or {}
        self.twitter_config = twitter_config
        self.caption_format = TextFormatter(caption)
        self.website_config = website_config

    @staticmethod
    def from_json(json_dict) -> 'ChannelConfig':
        handle = json_dict["handle"]
        queue_val = json_dict.get("queue")
        queue = None
        if queue_val:
            queue = QueueConfig.from_json(queue_val, handle)
        tags = {}
        tags_val = json_dict.get("tags")
        if tags_val:
            tags = {key: TagConfig.from_json(val) for key, val in tags_val.items()}
        twitter_config = None
        twitter_val = json_dict.get("twitter")
        if twitter_val:
            twitter_config = TwitterConfig.from_json(twitter_val)
        return ChannelConfig(
            handle,
            queue=queue,
            read_only=json_dict.get("read_only", False),
            send_folder=json_dict.get("send_folder"),
            note_time=json_dict.get("note_time", False),
            tags=tags,
            twitter_config=twitter_config,
            caption=json_dict.get("caption", ""),
            website_config=WebsiteConfig.from_json(json_dict.get("website")),
        )


class WorkshopConfig(ChatConfig):

    @staticmethod
    def from_json(json_dict) -> "WorkshopConfig":
        return WorkshopConfig(
            json_dict["handle"],
            duplicate_detection=json_dict.get("duplicate_detection", True),
            default_destination=json_dict.get("default_destination"),
        )


class QueueConfig(WorkshopConfig):
    def __init__(
            self,
            handle: Union[str, int],
            channel_handle: Union[str, int],
            *,
            duplicate_detection: bool = True,
            schedule: ScheduleConfig = None
    ):
        super().__init__(
            handle,
            duplicate_detection=duplicate_detection,
            default_destination=channel_handle
        )
        self.channel_handle = channel_handle
        self.schedule = schedule

    @staticmethod
    def from_json(json_dict: Dict[str, Any], channel_handle: Union[str, int]) -> 'QueueConfig':
        schedule = None
        schedule_val = json_dict.get("schedule")
        if schedule_val:
            schedule = ScheduleConfig.from_json(schedule_val)
        return QueueConfig(
            json_dict["handle"],
            channel_handle,
            duplicate_detection=json_dict.get("duplicate_detection", True),
            schedule=schedule
        )
