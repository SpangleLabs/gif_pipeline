from typing import Optional, List, TYPE_CHECKING

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
            callback_query: bytes
    ) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == "clear_delete_menu":
            self.cleared = True
            sent_msg = await self.send()
            return [sent_msg]
        # The "delete:" callback is handled by DeleteHelper
