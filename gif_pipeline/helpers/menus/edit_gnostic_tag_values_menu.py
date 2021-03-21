from typing import List, TYPE_CHECKING, Optional

from telethon import Button

from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.menus.edit_tag_values_menu import EditTagValuesMenu
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.message import Message
from gif_pipeline.tag_manager import TagManager
from gif_pipeline.video_tags import gnostic_tag_name_positive, gnostic_tag_name_negative

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper


class EditGnosticTagValuesMenu(EditTagValuesMenu):

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
        super().__init__(menu_helper, chat, cmd, video, send_helper, destination, tag_manager, tag_name)
        # We need to make a copy of the tags, so that edits elsewhere won't cause these to get saved to database early
        self.current_tags = self.current_tags.copy()
        self.tag_name_pos = gnostic_tag_name_positive(self.tag_name)
        self.tag_name_neg = gnostic_tag_name_negative(self.tag_name)

    @property
    def text(self) -> str:
        if not self.known_tag_values:
            return f"There are no known previous values for the tag \"{self.tag_name}\" going to that destination.\n" \
                   f"Please reply to this menu with a tag value to add."
        return f"Select which tags this video should have for \"{self.tag_name}\".\n" \
               f"Any you do not select, will be assumed to be rejected tags for this video.\n" \
               f"Press cancel to leave without saving changes."

    def page_center_buttons(self) -> List[Button]:
        return [self.button_done(), self.button_cancel()]

    def get_tag_value_status(self, tag_value: str) -> Optional[bool]:
        if tag_value in self.current_tags.list_values_for_tag(self.tag_name_pos):
            return True
        if tag_value in self.current_tags.list_values_for_tag(self.tag_name_neg):
            return False
        return None

    def text_for_tag_button(self, tag_value: str) -> str:
        tag_status = self.get_tag_value_status(tag_value)
        if tag_status is True:
            return f"✔️{tag_value}"
        if tag_status is False:
            return f"❌{tag_value}"
        return f"❌❓{tag_value}"

    def set_tag_value(self, tag_value: str) -> None:
        if self.get_tag_value_status(tag_value):
            self.current_tags.remove_tag_value(self.tag_name_pos, tag_value)
            self.current_tags.add_tag_value(self.tag_name_neg, tag_value)
        else:
            self.current_tags.add_tag_value(gnostic_tag_name_positive(self.tag_name), tag_value)
            self.current_tags.remove_tag_value(gnostic_tag_name_negative(self.tag_name), tag_value)

    async def handle_callback_done(self) -> List[Message]:
        # Save database when done, just for this tag
        self.send_helper.database.save_tags_for_key(self.video.message_data, self.current_tags, self.tag_name_pos)
        self.send_helper.database.save_tags_for_key(self.video.message_data, self.current_tags, self.tag_name_neg)
        # Return to menu
        return await self.return_to_menu()
