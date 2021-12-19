from abc import ABC, abstractmethod
from datetime import timedelta
from enum import Enum
from typing import Union, Dict, Any, Optional

import isodate


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
    ):
        self.min_time = min_time
        self.max_time = max_time
        self.order = order or ScheduleOrder.RANDOM

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
        return ScheduleConfig(
            min_time=min_time,
            max_time=max_time,
            order=order
        )


class ChatConfig(ABC):
    def __init__(
            self,
            handle: Union[str, int],
            *,
            duplicate_detection: bool = True
    ):
        self.handle = handle
        self.duplicate_detection = duplicate_detection
        self.read_only = False

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
    ):
        super().__init__(handle)
        self.queue = queue
        self.read_only = read_only
        self.send_folder = send_folder
        self.note_time = note_time
        self.tags = tags or {}

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
        return ChannelConfig(
            handle,
            queue=queue,
            read_only=json_dict.get("read_only", False),
            send_folder=json_dict.get("send_folder"),
            note_time=json_dict.get("note_time", False),
            tags=tags
        )


class WorkshopConfig(ChatConfig):

    @staticmethod
    def from_json(json_dict) -> 'WorkshopConfig':
        return WorkshopConfig(
            json_dict['handle'],
            duplicate_detection=json_dict.get("duplicate_detection", True)
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
        super().__init__(handle, duplicate_detection=duplicate_detection)
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
