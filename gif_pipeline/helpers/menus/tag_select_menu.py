from typing import TYPE_CHECKING, Dict, List, Optional, Set

from telethon import Button

from gif_pipeline.chat import Channel, Chat
from gif_pipeline.helpers.menus.menu import Menu
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper
    from gif_pipeline.helpers.send_helper import GifSendHelper


class TagSelectMenu(Menu):
    select_callback = b"select"
    cancel_callback = b"cancel"

    def __init__(
        self,
        menu_helper: "MenuHelper",
        chat: Chat,
        cmd: Message,
        video: Message,
        send_helper: "GifSendHelper",
        destination: Channel,
        missing_tags: Set[str],
    ):
        super().__init__(menu_helper, chat, cmd, video)
        self.send_helper = send_helper
        self.destination = destination
        self.missing_tags = sorted(list(missing_tags))

    @property
    def text(self) -> str:
        return "Which tag would you like to edit?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return [
            [Button.inline(tag_name, f"{self.select_callback.decode()}:{i}")]
            for i, tag_name in enumerate(self.missing_tags)
        ]

    async def handle_callback_query(
        self,
        callback_query: bytes,
        sender_id: int,
    ) -> Optional[List[Message]]:
        if callback_query == self.cancel_callback:
            await self.delete()
            return []
        if callback_query.startswith(self.select_callback):
            tag_name = self.missing_tags[int(callback_query.split(b":")[1])]
            return await self.menu_helper.edit_tag_values(
                self.chat, self.cmd, self.video, self.send_helper, self.destination, tag_name
            )

    @classmethod
    def json_name(cls) -> str:
        return "tag_select_menu"

    def to_json(self) -> Dict:
        return {
            "cmd_msg_id": self.cmd_msg_id,
            "destination_id": self.destination.chat_data.chat_id,
            "missing_tags": self.missing_tags,
        }

    @classmethod
    def from_json(
        cls,
        json_data: Dict,
        menu_helper: "MenuHelper",
        chat: Chat,
        video: Message,
        send_helper,
        all_channels: List[Channel],
    ) -> "TagSelectMenu":
        destination = next(filter(lambda x: x.chat_data.chat_id == json_data["destination_id"], all_channels), None)
        return TagSelectMenu(
            menu_helper,
            chat,
            chat.message_by_id(json_data["cmd_msg_id"]),
            video,
            send_helper,
            destination,
            set(json_data["missing_tags"]),
        )
