from typing import List

from gif_pipeline.helpers.menus.edit_tag_values_menu import EditTagValuesMenu
from gif_pipeline.message import Message


class EditSingleTagValuesMenu(EditTagValuesMenu):

    @property
    def text(self) -> str:
        if not self.known_tag_values:
            return f"There are no known previous values for the tag \"{self.tag_name}\" going to that destination.\n" \
                   f"Please reply to this menu with the tag value to set."
        return f"Select which single tag this video should have for \"{self.tag_name}\":"

    async def handle_callback_tag_edit(self, callback_query: bytes) -> List[Message]:
        await self.process_callback_tag_edit(callback_query)
        return await self.handle_callback_done()
