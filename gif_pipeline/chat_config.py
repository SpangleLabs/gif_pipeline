from abc import ABC, abstractmethod
from enum import Enum
from typing import Union, Dict, Any, Optional, List


class TagType(Enum):
    NORMAL = "normal"  # Store a list of values for this tag
    SINGLE = "single"  # Store a single value for this tag
    TEXT = "text"  # Store a text string for this tag, do not list the other values
    GNOSTIC = "gnostic"  # Store a list of positive and negative values for this tag


class TagConfig:
    def __init__(self, tag_type: TagType):
        self.type = tag_type

    @staticmethod
    @abstractmethod
    def from_json(json_dict: Dict[str, Any]) -> 'TagConfig':
        tag_type_str = json_dict.get("type", "normal")
        try:
            tag_type = TagType[tag_type_str.upper()]
        except KeyError as e:
            raise KeyError(f"Invalid tag type, \"{tag_type_str}\": {e}")
        return TagConfig(tag_type)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(type={self.type})"


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
    ):
        super().__init__(handle, duplicate_detection=duplicate_detection)
        self.channel_handle = channel_handle

    @staticmethod
    def from_json(json_dict: Dict[str, Any], channel_handle: Union[str, int]) -> 'QueueConfig':
        return QueueConfig(
            json_dict["handle"],
            channel_handle,
            duplicate_detection=json_dict.get("duplicate_detection", True),
        )
