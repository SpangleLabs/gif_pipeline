from typing import List, TYPE_CHECKING, Optional, Dict

from telethon import Button

from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.menus.edit_tag_values_menu import EditTagValuesMenu
from gif_pipeline.message import Message
from gif_pipeline.video_tags import gnostic_tag_name_positive, gnostic_tag_name_negative, VideoTags

if TYPE_CHECKING:
    from gif_pipeline.tag_manager import TagManager
    from gif_pipeline.helpers.send_helper import GifSendHelper
    from gif_pipeline.helpers.menu_helper import MenuHelper


class EditGnosticTagValuesMenu(EditTagValuesMenu):

    def __init__(
            self,
            menu_helper: 'MenuHelper',
            chat: Chat,
            cmd: Message,
            video: Message,
            send_helper: 'GifSendHelper',
            destination: Channel,
            tag_manager: 'TagManager',
            tag_name: str
    ):
        super().__init__(menu_helper, chat, cmd, video, send_helper, destination, tag_manager, tag_name)
        # We need to make a copy of the tags, so that edits elsewhere won't cause these to get saved to database early
        self.original_tags = self.current_tags
        self.current_tags = self.current_tags.copy()
        self.tag_name_pos = gnostic_tag_name_positive(self.tag_name)
        self.tag_name_neg = gnostic_tag_name_negative(self.tag_name)
        # Total list of tags also needs changing, because we have positive and negative values to list
        all_values_pos = self.tag_manager.get_values_for_tag(self.tag_name_pos, [destination, chat])
        all_values_neg = self.tag_manager.get_values_for_tag(self.tag_name_neg, [destination, chat])
        self.known_tag_values = sorted(all_values_pos.union(all_values_neg))
        self.new_tags = set()

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
            self.current_tags.add_tag_value(self.tag_name_pos, tag_value)
            self.current_tags.remove_tag_value(self.tag_name_neg, tag_value)

    async def handle_callback_done(self) -> List[Message]:
        # For all unset values, set to negative
        for tag_value in self.known_tag_values:
            if self.get_tag_value_status(tag_value) is None:
                self.current_tags.add_tag_value(self.tag_name_neg, tag_value)
        # Save database when done, just for this tag
        self.send_helper.database.save_tags_for_key(self.video.message_data, self.current_tags, self.tag_name_pos)
        self.send_helper.database.save_tags_for_key(self.video.message_data, self.current_tags, self.tag_name_neg)
        # Update the original video's VideoTag object from database
        tag_entries = self.send_helper.database.get_tags_for_message(self.video.message_data)
        self.original_tags.update_from_database(tag_entries)
        # Return to menu
        return await self.return_to_menu()

    def update_known_tag_values(self, new_tag: str) -> None:
        self.new_tags.add(new_tag)
        chats = [self.destination, self.chat]
        all_values_pos = self.tag_manager.get_values_for_tag(self.tag_name_pos, chats)
        all_values_neg = self.tag_manager.get_values_for_tag(self.tag_name_neg, chats)
        self.known_tag_values = sorted(all_values_pos.union(all_values_neg).union(self.new_tags))

    @classmethod
    def json_name(cls) -> str:
        return "edit_gnostic_tag_values_menu"

    def to_json(self) -> Dict:
        return {
            "cmd_msg_id": self.cmd.message_data.message_id,
            "destination_id": self.destination.chat_data.chat_id,
            "tag_name": self.tag_name,
            "page_num": self.page_num,
            "current_tags": self.current_tags.to_json(),
            "new_tags": list(self.new_tags)
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
            tag_manager: 'TagManager'
    ) -> 'EditTagValuesMenu':
        destination = next(filter(lambda x: x.chat_data.chat_id == json_data["destination_id"], all_channels), None)
        menu = EditGnosticTagValuesMenu(
            menu_helper,
            chat,
            chat.message_by_id(json_data["cmd_msg_id"]),
            video,
            send_helper,
            destination,
            tag_manager,
            json_data["tag_name"]
        )
        menu.current_tags = VideoTags.from_json(json_data["current_tags"])
        menu.page_num = json_data["page_num"]
        menu.new_tags = set(json_data["new_tags"])
        return menu
