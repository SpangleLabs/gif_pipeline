from typing import TYPE_CHECKING, Dict, List, Optional, Set

from telethon import Button

from gif_pipeline.chat import Channel, Chat
from gif_pipeline.helpers.menus.menu import Menu
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper
    from gif_pipeline.helpers.send_helper import GifSendHelper


class CheckTagsMenu(Menu):
    send_callback = b"send"
    edit_callback = b"edit"
    cancel_callback = b"cancel"

    def __init__(
            self,
            menu_helper: 'MenuHelper',
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: 'GifSendHelper',
            destination: Channel,
            missing_tags: Set[str]
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.destination = destination
        self.missing_tags = missing_tags
        self.cancelled = False

    @property
    def text(self) -> str:
        dest_tags = self.destination.config.tags
        msg = f"The destination suggests videos should be tagged with:\n"
        for tag in dest_tags.keys():
            if tag in self.missing_tags:
                msg += f" - <b>{tag}</b>\n"
            else:
                msg += f" - {tag}\n"
        msg += f"This video is missing {len(self.missing_tags)} tags, bold in the above list"
        return msg

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        if not self.cancelled:
            return [
                [Button.inline("Send anyway", self.send_callback)],
                [Button.inline("Edit tags", self.edit_callback)],
                [Button.inline("Cancel", self.cancel_callback)]
            ]

    async def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int,
    ) -> Optional[List[Message]]:
        if callback_query == self.cancel_callback:
            self.cancelled = True
            sent_msg = await self.send()
            return [sent_msg]
        if callback_query == self.edit_callback:
            if len(self.missing_tags) != 1:
                return await self.menu_helper.edit_tag_select(
                    self.chat, self.cmd, self.video, self.send_helper, self.destination, self.missing_tags
                )
            missing_tag_name = next(iter(self.missing_tags))
            return await self.menu_helper.edit_tag_values(
                self.chat, self.cmd, self.video, self.send_helper, self.destination, missing_tag_name
            )
        if callback_query == self.send_callback:
            return await self.menu_helper.confirmation_menu(
                self.chat, self.cmd, self.video, self.send_helper, self.destination
            )

    @classmethod
    def json_name(cls) -> str:
        return "check_tags_menu"

    def to_json(self) -> Dict:
        return {
            "cmd_msg_id": self.cmd_msg_id,
            "destination_id": self.destination.chat_data.chat_id,
            "missing_tags": list(self.missing_tags),
            "cancelled": self.cancelled
        }

    @classmethod
    def from_json(
            cls,
            json_data: Dict,
            menu_helper: 'MenuHelper',
            chat: Chat,
            video: Message,
            send_helper: 'GifSendHelper'
    ) -> 'Menu':
        menu = CheckTagsMenu(
            menu_helper,
            chat,
            chat.message_by_id(json_data["cmd_msg_id"]),
            video,
            send_helper,
            send_helper.get_destination_from_name(json_data["destination_id"]),
            set(json_data["missing_tags"])
        )
        menu.cancelled = json_data["cancelled"]
        return menu
