import datetime
from abc import abstractmethod
from typing import TYPE_CHECKING, Dict, List, Optional

from telethon import Button

from gif_pipeline.chat import Chat
from gif_pipeline.menu_cache import SentMenu
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper


def delta_to_string(delta: datetime.timedelta) -> str:
    days, remainder = divmod(delta.total_seconds(), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    day_word = "day" if days == 1 else "days"
    hour_word = "hour" if hours == 1 else "hours"
    minute_word = "minute" if minutes == 1 else "minutes"
    if days:
        return f"{days:.0f} {day_word}, {hours:.0f} {hour_word}"
    return f"{hours:.0f} {hour_word}, {minutes:.0f} {minute_word}"


class Menu:

    def __init__(self, menu_helper: 'MenuHelper', chat: Chat, cmd: Optional[Message], video: Message):
        self.menu_helper = menu_helper
        self.chat = chat
        self.cmd = cmd
        self.video = video

    def add_self_to_cache(self, menu_msg: Message):
        self.menu_helper.menu_cache.add_menu(SentMenu(self, menu_msg))

    def allows_sender(self, sender_id: int) -> bool:
        if self.cmd:
            return sender_id == self.cmd.message_data.sender_id
        return True

    @property
    def cmd_msg_id(self) -> Optional[int]:
        if self.cmd:
            return self.cmd.message_data.message_id
        return None

    @property
    @abstractmethod
    def text(self) -> str:
        pass

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return None

    async def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        pass

    async def send_as_reply(self, reply_to: Message) -> Message:
        menu_msg = await self.menu_helper.send_text_reply(
            self.chat,
            reply_to,
            self.text,
            buttons=self.buttons
        )
        self.add_self_to_cache(menu_msg)
        return menu_msg

    async def edit_message(self, old_msg: Message) -> Message:
        menu_msg = await self.menu_helper.edit_message(
            self.chat,
            old_msg,
            new_text=self.text,
            new_buttons=self.buttons
        )
        if self.buttons:
            self.add_self_to_cache(menu_msg)
        else:
            self.menu_helper.menu_cache.remove_menu_by_video(self.video)
        return menu_msg

    async def send(self) -> Message:
        menu = self.menu_helper.menu_cache.get_menu_by_video(self.video)
        if menu:
            return await self.edit_message(menu.msg)
        return await self.send_as_reply(self.video)

    async def repost(self) -> Message:
        menu = self.menu_helper.menu_cache.get_menu_by_video(self.video)
        if menu:
            await self.delete()
        return await self.send_as_reply(self.video)

    async def delete(self) -> None:
        await self.menu_helper.delete_menu_for_video(self.chat, self.video)

    def capture_text(self) -> bool:
        return False

    async def handle_text(self, text: str) -> Optional[List[Message]]:
        return None

    @classmethod
    @abstractmethod
    def json_name(cls) -> str:
        pass

    @abstractmethod
    def to_json(self) -> Dict:
        pass

    @classmethod
    @abstractmethod
    def from_json(cls, json_data: Dict) -> 'Menu':
        pass
