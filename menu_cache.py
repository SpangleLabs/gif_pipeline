from collections import defaultdict
from typing import Optional

from message import Message


class MenuOwnershipCache:
    def __init__(self) -> None:
        self.cache = defaultdict(lambda: dict())

    def add_menu(self, chat_id: int, message_id: int, requester_id: int) -> None:
        self.cache[chat_id][message_id] = requester_id

    def add_menu_msg(self, message: Message, requester_id: int) -> None:
        self.add_menu(message.chat_data.chat_id, message.message_data.message_id, requester_id)

    def get_sender_for_message(self, chat_id: int, message_id: int) -> Optional[int]:
        return self.cache[chat_id].get(message_id)

    def remove_menu(self, chat_id: int, message_id: int) -> None:
        del self.cache[chat_id][message_id]

    def remove_menu_msg(self, message: Message) -> None:
        self.remove_menu(message.chat_data.chat_id, message.message_data.message_id)
