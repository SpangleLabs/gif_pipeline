from typing import Optional, List

from telethon import Button

from gif_pipeline.helpers.menus.edit_tag_values_menu import EditTagValuesMenu
from gif_pipeline.message import Message


class EditTextTagValuesMenu(EditTagValuesMenu):
    cancel_callback = b"cancel"

    @property
    def text(self) -> str:
        return f"Please reply to this menu with the value for the \"{self.tag_name}\" tag for this video."

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return [[Button.inline("❌Cancel", self.cancel_callback)]]

    def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.cancel_callback:
            return await self.handle_callback_done()

    async def handle_text(self, text: str) -> Optional[List[Message]]:
        self.set_tag_value(text)
        return await self.handle_callback_done()
