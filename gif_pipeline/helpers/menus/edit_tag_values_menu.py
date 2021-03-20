from typing import List, Optional, TYPE_CHECKING

from telethon import Button

from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.menus.menu import Menu
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.message import Message
from gif_pipeline.tag_manager import TagManager

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper


class EditTagValuesMenu(Menu):
    complete_callback = b"done"
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
            send_helper: GifSendHelper,
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
            return [[self.button_done()]]
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
        buttons.append(self.button_done())
        if self.page_num < len(self.paged_tag_values) - 1:
            buttons.append(Button.inline("➡️Next", self.next_callback))
        return buttons

    def button_done(self) -> Button:
        return Button.inline("🖊️️️Done", self.complete_callback)

    def button_for_tag(self, tag_value: str, i: int) -> Button:
        has_tag = tag_value in self.current_tags.list_values_for_tag(self.tag_name)
        title = tag_value
        if has_tag:
            title = f"✔️{title}"
        value_num = self.page_num * self.page_width * self.page_height + i
        return Button.inline(title, f"{self.tag_callback.decode()}:{value_num}")

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.complete_callback:
            return await self.handle_callback_done()
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
        missing_tags = self.send_helper.missing_tags_for_video(self.video, self.destination)
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
        # Update known tag values
        chats = [self.destination, self.chat]
        self.known_tag_values = sorted(self.tag_manager.get_values_for_tag(self.tag_name, chats))
        return [await self.send()]
