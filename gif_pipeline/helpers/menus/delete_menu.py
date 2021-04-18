from typing import Optional, List, TYPE_CHECKING, Dict

from telethon import Button

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.menus.menu import Menu
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper


class DeleteMenu(Menu):
    def __init__(self, menu_helper: 'MenuHelper', chat: Chat, cmd_msg: Message, video: Message, prefix_str: str):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.prefix_str = prefix_str
        self.cleared = False

    @property
    def text(self):
        if self.cleared:
            return self.prefix_str
        return self.prefix_str + "\nWould you like to delete the message family?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        if self.cleared:
            return None
        return [
            [Button.inline("Yes please", f"delete:{self.video.message_data.message_id}")],
            [Button.inline("No thanks", f"clear_delete_menu")]
        ]

    async def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int,
    ) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == "clear_delete_menu":
            self.cleared = True
            sent_msg = await self.send()
            return [sent_msg]
        # The "delete:" callback is handled by DeleteHelper

    @classmethod
    def json_name(cls) -> str:
        return "delete_menu"

    def to_json(self) -> Dict:
        return {
            "cmd_msg_id": self.cmd_msg_id,
            "prefix_str": self.prefix_str,
            "cleared": self.cleared
        }

    @classmethod
    def from_json(
            cls,
            json_data: Dict,
            menu_helper: 'MenuHelper',
            chat: Chat,
            video: Message
    ) -> 'Menu':
        menu = DeleteMenu(
            menu_helper,
            chat,
            chat.message_by_id(json_data["cmd_msg_id"]),
            video,
            json_data["prefix_str"]
        )
        menu.cleared = json_data["cleared"]
        return menu
