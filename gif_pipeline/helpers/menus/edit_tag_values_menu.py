from typing import List, Optional, TYPE_CHECKING, Dict, Type

from telethon import Button

from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.menus.menu import Menu
from gif_pipeline.message import Message
from gif_pipeline.tag_manager import TagManager

if TYPE_CHECKING:
    from gif_pipeline.helpers.send_helper import GifSendHelper
    from gif_pipeline.helpers.menu_helper import MenuHelper


class EditTagValuesMenu(Menu):
    complete_callback = b"done"
    cancel_callback = b"cancel"
    next_callback = b"next"
    prev_callback = b"prev"
    tag_callback = b"tag"
    page_height = 5
    page_width = 3

    def __init__(
            self,
            menu_helper: 'MenuHelper',
            chat: Chat,
            cmd: Message,
            video: Message,
            send_helper: 'GifSendHelper',
            destination: Channel,
            tag_manager: TagManager,
            tag_name: str
    ):
        super().__init__(menu_helper, chat, cmd, video)
        self.send_helper = send_helper
        self.destination = destination
        self.tag_manager = tag_manager
        self.tag_name = tag_name
        self.known_tag_values = sorted(self.tag_manager.get_values_for_tag(tag_name, [destination, chat]))
        self.page_num = 0
        self.current_tags = self.video.tags(self.menu_helper.database)

    @property
    def paged_tag_values(self) -> List[List[str]]:
        len_values = len(self.known_tag_values)
        page_size = self.page_height * self.page_width
        return [self.known_tag_values[i: i + page_size] for i in range(0, len_values, page_size)]

    @property
    def text(self) -> str:
        if not self.known_tag_values:
            return f"There are no known previous values for the tag \"{self.tag_name}\" going to that destination.\n" \
                   f"Please reply to this menu with a tag value to add."
        return f"Select which tags this video should have for \"{self.tag_name}\":"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        tag_buttons = self.tag_buttons()
        page_buttons = self.page_buttons()
        return tag_buttons + [page_buttons]

    def tag_buttons(self) -> List[List[Button]]:
        if not self.known_tag_values:
            return []
        current_page = self.paged_tag_values[self.page_num]
        columns = (len(current_page) // self.page_height) + (len(current_page) % self.page_height > 0)
        return [
            [self.button_for_tag(tag_value, i+j) for j, tag_value in enumerate(current_page[i:i+columns])]
            for i in range(0, len(current_page), columns)
        ]

    def page_buttons(self) -> List[Button]:
        buttons = []
        if self.page_num > 0:
            buttons.append(Button.inline("⬅️Prev", self.prev_callback))
        buttons += self.page_center_buttons()
        if self.page_num < len(self.paged_tag_values) - 1:
            buttons.append(Button.inline("➡️Next", self.next_callback))
        return buttons

    def page_center_buttons(self) -> List[Button]:
        return [self.button_done()]

    def button_done(self) -> Button:
        return Button.inline("🖊️️️Done", self.complete_callback)

    def button_cancel(self) -> Button:
        return Button.inline("🔙Cancel", self.cancel_callback)

    def button_for_tag(self, tag_value: str, i: int) -> Button:
        title = self.text_for_tag_button(tag_value)
        value_num = self.page_num * self.page_width * self.page_height + i
        return Button.inline(title, f"{self.tag_callback.decode()}:{value_num}")

    def text_for_tag_button(self, tag_value: str) -> str:
        if tag_value in self.current_tags.list_values_for_tag(self.tag_name):
            return f"✔️{tag_value}"
        return tag_value

    async def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int,
    ) -> Optional[List[Message]]:
        if callback_query == self.complete_callback:
            return await self.handle_callback_done()
        if callback_query == self.cancel_callback:
            return await self.handle_callback_cancel()
        if callback_query == self.next_callback:
            self.page_num += 1
            return [await self.send()]
        if callback_query == self.prev_callback:
            self.page_num -= 1
            return [await self.send()]
        if callback_query.startswith(self.tag_callback):
            return await self.handle_callback_tag_edit(callback_query)

    async def handle_callback_tag_edit(self, callback_query: bytes) -> List[Message]:
        self.set_tag_value(self.known_tag_values[int(callback_query.split(b":")[1])])
        return [await self.send()]

    def set_tag_value(self, tag_value: str) -> None:
        self.current_tags.toggle_tag_value(self.tag_name, tag_value)
        self.menu_helper.database.save_tags(self.video.message_data, self.current_tags)

    async def handle_callback_done(self) -> List[Message]:
        return await self.return_to_menu()

    async def handle_callback_cancel(self) -> List[Message]:
        return await self.return_to_menu()

    async def return_to_menu(self) -> List[Message]:
        missing_tags = self.tag_manager.missing_tags_for_video(self.video, self.destination, self.chat)
        if missing_tags:
            return await self.menu_helper.additional_tags_menu(
                self.chat, self.cmd, self.video, self.send_helper, self.destination, missing_tags
            )
        return await self.menu_helper.confirmation_menu(
            self.chat, self.cmd, self.video, self.send_helper, self.destination
        )

    def capture_text(self) -> bool:
        return True

    async def handle_text(self, text: str) -> Optional[List[Message]]:
        self.set_tag_value(text)
        self.update_known_tag_values(text)
        return [await self.send()]

    def update_known_tag_values(self, new_tag: str) -> None:
        chats = [self.destination, self.chat]
        self.known_tag_values = sorted(self.tag_manager.get_values_for_tag(self.tag_name, chats))

    @classmethod
    def json_name(cls) -> str:
        return "edit_tag_values_menu"

    def to_json(self) -> Dict:
        return {
            "cmd_msg_id": self.cmd_msg_id,
            "destination_id": self.destination.chat_data.chat_id,
            "tag_name": self.tag_name,
            "page_num": self.page_num
        }

    @classmethod
    def from_json(
            cls,
            json_data: Dict,
            menu_helper: 'MenuHelper',
            chat: Chat,
            video: Message,
            send_helper: 'GifSendHelper',
            all_channels: List[Channel],
            tag_manager: TagManager
    ) -> 'EditTagValuesMenu':
        destination = next(filter(lambda x: x.chat_data.chat_id == json_data["destination_id"], all_channels), None)
        menu = cls(
            menu_helper,
            chat,
            chat.message_by_id(json_data["cmd_msg_id"]),
            video,
            send_helper,
            destination,
            tag_manager,
            json_data["tag_name"]
        )
        menu.page_num = json_data["page_num"]
        return menu
