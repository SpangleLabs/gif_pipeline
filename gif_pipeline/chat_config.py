from abc import ABC, abstractmethod
from typing import Union, Dict, Any


class ChatConfig(ABC):
    def __init__(
            self,
            handle: Union[str, int],
            *,
            queue: bool = False,
            duplicate_detection: bool = True
    ):
        self.handle = handle
        self.queue = queue
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
            queue: bool = False,
            duplicate_detection: bool = True,
            read_only: bool = False
    ):
        super().__init__(handle, queue=queue, duplicate_detection=duplicate_detection)
        self.read_only = read_only

    @staticmethod
    def from_json(json_dict) -> 'ChannelConfig':
        return ChannelConfig(
            json_dict['handle'],
            queue=json_dict['queue'],
            read_only=json_dict.get("read_only", False)
        )


class WorkshopConfig(ChatConfig):

    @staticmethod
    def from_json(json_dict) -> 'WorkshopConfig':
        return WorkshopConfig(json_dict['handle'], duplicate_detection=json_dict.get("duplicate_detection", True))