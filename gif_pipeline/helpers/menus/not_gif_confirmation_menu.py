from typing import Optional, List, TYPE_CHECKING, Dict

from telethon import Button

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.menus.menu import Menu
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper


class NotGifConfirmationMenu(Menu):
    clear_menu = b"clear_not_gif_menu"
    send_str = "send_str"

    def __init__(
            self,
            menu_helper: 'MenuHelper',
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            dest_str: str
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.dest_str = dest_str

    @property
    def text(self) -> str:
        return "It looks like this video has not been giffed. Are you sure you want to send it?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        button_data = f"{self.send_str}:{self.dest_str}"
        return [
            [Button.inline("Yes, I am sure", button_data)],
            [Button.inline("No thanks!", self.clear_menu)]
        ]

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.clear_menu:
            await self.delete()
            return []
        # Handle sending if the user is sure
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.send_str:
            _, dest_str = split_data
            return await self.send_helper.handle_dest_str(
                self.chat, self.cmd, self.video, dest_str, self.owner_id
            )

    @classmethod
    def json_name(cls) -> str:
        return "not_gif_confirmation_menu"

    def to_json(self) -> Dict:
        return {
            "cmd_msg_id": self.cmd.message_data.message_id,
            "dest_str": self.dest_str
        }

    @classmethod
    def from_json(
            cls,
            json_data: Dict,
            menu_helper: MenuHelper,
            chat: Chat,
            video: Message,
            send_helper: GifSendHelper
    ) -> 'Menu':
        return NotGifConfirmationMenu(
            menu_helper,
            chat,
            chat.message_by_id(json_data["cmd_msg_id"]),
            video,
            send_helper,
            json_data["dest_str"]
        )
