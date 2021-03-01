from abc import ABC, abstractmethod
from typing import TypeVar, Optional

C = TypeVar('C', bound='ChatData')


class ChatData(ABC):
    def __init__(self, chat_id: int, username: Optional[str], title: str) -> None:
        self.chat_id = chat_id
        self.username = username
        self.title = title

    @property
    @abstractmethod
    def directory(self) -> str:
        pass

    def telegram_link_for_message(self, message_data: 'MessageData') -> str:
        handle = abs(self.chat_id)
        if str(self.chat_id).startswith("-100"):
            handle = str(self.chat_id)[4:]
        return f"https://t.me/c/{handle}/{message_data.message_id}"


class ChannelData(ChatData):

    @property
    def directory(self) -> str:
        return f"store/channels/{self.username or self.chat_id}/"

    def telegram_link_for_message(self, message_data: 'MessageData') -> str:
        if self.username is None:
            return super().telegram_link_for_message(message_data)
        return f"https://t.me/{self.username}/{message_data.message_id}"


class WorkshopData(ChatData):

    @property
    def directory(self) -> str:
        return f"store/workshop/{self.chat_id}/"