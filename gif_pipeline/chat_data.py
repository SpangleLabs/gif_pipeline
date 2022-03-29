from abc import ABC, abstractmethod
from typing import TypeVar, Optional, Union

from gif_pipeline.chat_config import ChatConfig, ChannelConfig, WorkshopConfig
from gif_pipeline.message import MessageData

C = TypeVar('C', bound='ChatData')


def chat_id_matches(id1: Union[int, str], id2: Union[int, str]) -> bool:
    prefix = "-100"
    id1_str = str(id1)
    id2_str = str(id2)
    if id1_str.startswith(prefix):
        id1_str = id1_str[len(prefix):]
    if id2_str.startswith(prefix):
        id2_str = id2_str[len(prefix):]
    return id1_str == id2_str


def chat_username_matches(username1: Optional[str], username2: Optional[str]) -> bool:
    if username1 is None:
        return False
    if username2 is None:
        return False
    return username1.casefold() == username2.casefold()


class ChatData(ABC):
    def __init__(
            self,
            chat_id: int,
            access_hash: int,
            username: Optional[str],
            title: str,
            broadcast: bool,
            megagroup: bool
    ) -> None:
        self.chat_id = chat_id
        self.access_hash = access_hash
        self.username = username
        self.title = title
        self.broadcast = broadcast
        self.megagroup = megagroup

    @property
    @abstractmethod
    def directory(self) -> str:
        pass

    def telegram_link_for_message(self, message_data: 'MessageData') -> str:
        handle = abs(self.chat_id)
        if str(self.chat_id).startswith("-100"):
            handle = str(self.chat_id)[4:]
        return f"https://t.me/c/{handle}/{message_data.message_id}"

    @abstractmethod
    def matches_config(self, conf: ChatConfig) -> bool:
        return self.matches_handle(str(conf.handle))

    def matches_handle(self, handle: str) -> bool:
        return chat_username_matches(self.username, handle) or chat_id_matches(self.chat_id, handle)


class ChannelData(ChatData):

    @property
    def directory(self) -> str:
        return f"store/channels/{self.username or self.chat_id}/"

    def telegram_link_for_message(self, message_data: 'MessageData') -> str:
        if self.username is None:
            return super().telegram_link_for_message(message_data)
        return f"https://t.me/{self.username}/{message_data.message_id}"

    def matches_config(self, conf: ChatConfig) -> bool:
        return isinstance(conf, ChannelConfig) and super().matches_config(conf)


class WorkshopData(ChatData):

    @property
    def directory(self) -> str:
        return f"store/workshop/{self.chat_id}/"

    def matches_config(self, conf: ChatConfig) -> bool:
        return isinstance(conf, WorkshopConfig) and super().matches_config(conf)
