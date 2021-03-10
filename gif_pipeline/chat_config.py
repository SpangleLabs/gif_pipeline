from abc import ABC, abstractmethod
from typing import Union, Dict, Any, Optional


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
            note_time: bool = False
    ):
        super().__init__(handle)
        self.read_only = read_only
        self.send_folder = send_folder
        self.note_time = note_time
        self.queue = queue

    @staticmethod
    def from_json(json_dict) -> 'ChannelConfig':
        queue_val = json_dict.get("queue")
        queue = None
        if queue_val:
            queue = QueueConfig.from_json(queue_val)
        return ChannelConfig(
            json_dict['handle'],
            queue=queue,
            read_only=json_dict.get("read_only", False),
            send_folder=json_dict.get("send_folder"),
            note_time=json_dict.get("note_time", False)
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
            *,
            duplicate_detection: bool = True,
    ):
        super().__init__(handle, duplicate_detection=duplicate_detection)
        self.handle = handle

    @staticmethod
    def from_json(json_dict: Dict[str, Any]) -> 'QueueConfig':
        return QueueConfig(
            json_dict["handle"],
            duplicate_detection=json_dict.get("duplicate_detection", True),
        )
