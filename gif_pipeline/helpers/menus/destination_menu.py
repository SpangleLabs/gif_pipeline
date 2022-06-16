from typing import List, Optional, TYPE_CHECKING, Dict

from telethon import Button

from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.menus.menu import Menu
from gif_pipeline.message import Message
from gif_pipeline.tag_manager import TagManager

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper
    from gif_pipeline.helpers.send_helper import GifSendHelper


class DestinationMenu(Menu):
    confirm_send = "confirm_send"
    folder = "send_folder"
    choose_destination = "choose_manual"

    def __init__(
        self,
        menu_helper: "MenuHelper",
        chat: Chat,
        cmd_msg: Message,
        video: Message,
        send_helper: "GifSendHelper",
        channels: List[Channel],
        tag_manager: TagManager,
        manual_select: bool = False
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.channels = channels
        self.tag_manager = tag_manager
        self.current_folder = None
        self.manual_select = manual_select

    @property
    def default_destination(self) -> Optional[Channel]:
        default_handle = self.chat.config.default_dest_handle
        if default_handle is None:
            return None
        default_chats = [channel for channel in self.channels if channel.chat_data.matches_handle(default_handle)]
        if len(default_chats) == 1:
            return default_chats[0]
        return None

    @property
    def text(self) -> str:
        if self.default_destination and not self.manual_select:
            default_title = self.default_destination.chat_data.title
            return f"This chat has a default destination of: {default_title}\nWould you like to send this video there?"
        return "Which channel should this video be sent to?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        if self.default_destination and not self.manual_select:
            return [
                [Button.inline("Yes", f"{self.confirm_send}:{self.default_destination.chat_data.chat_id}")],
                [Button.inline("No, choose a destination", f"{self.choose_destination}")]
            ]
        buttons = []
        folders = set()
        channels = set()
        for channel in self.channels:
            if channel.config.send_folder is None:
                if self.current_folder is None:
                    channels.add(channel)
            else:
                if self.current_folder is None:
                    folders.add(channel.config.send_folder.split("/")[0])
                else:
                    if channel.config.send_folder == self.current_folder:
                        channels.add(channel)
                    if channel.config.send_folder.startswith(self.current_folder + "/"):
                        folders.add(channel.config.send_folder[len(self.current_folder + "/"):].split("/")[0])
        # Create folder buttons
        for folder in sorted(folders):
            buttons.append(Button.inline(
                "📂: " + folder,
                f"{self.folder}:{folder}"
            ))
        # Create channel buttons
        for channel in sorted(channels, key=lambda chan: chan.chat_data.title):
            buttons.append(Button.inline(
                channel.chat_data.title,
                f"{self.confirm_send}:{channel.chat_data.chat_id}"
            ))
        # Create back button
        if self.current_folder is not None:
            buttons.append(Button.inline(
                "🔙 Back",
                f"{self.folder}:/"
            ))
        return [[b] for b in buttons]

    async def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int,
    ) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.choose_destination:
            self.manual_select = True
            return [await self.send()]
        if split_data[0] == self.confirm_send:
            destination_id = split_data[1]
            destination = self.send_helper.get_destination_from_name(destination_id)
            missing_tags = self.tag_manager.missing_tags_for_video(self.video, destination, self.chat)
            if missing_tags:
                return await self.menu_helper.additional_tags_menu(
                    self.chat, self.cmd, self.video, self.send_helper, destination, missing_tags
                )
            return await self.menu_helper.confirmation_menu(
                self.chat, self.cmd, self.video, self.send_helper, destination
            )
        if split_data[0] == self.folder:
            next_folder = split_data[1]
            if next_folder == "/":
                if self.current_folder is None or "/" not in self.current_folder:
                    folder = None
                else:
                    folder = "/".join(self.current_folder.split("/")[:-1])
            else:
                folder = next_folder
                if self.current_folder is not None:
                    folder = self.current_folder + "/" + next_folder
            self.current_folder = folder
            return [await self.send()]

    @classmethod
    def json_name(cls) -> str:
        return "destination_menu"

    def to_json(self) -> Dict:
        return {
            "cmd_msg_id": self.cmd_msg_id,
            "channel_ids": [channel.chat_data.chat_id for channel in self.channels],
            "current_folder": self.current_folder,
            "manual_select": self.manual_select,
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
            tag_manager
    ) -> 'DestinationMenu':
        channels = []
        for channel_id in json_data["channel_ids"]:
            channels.append(
                next(filter(lambda x: x.chat_data.chat_id == channel_id, all_channels), None)
            )
        menu = DestinationMenu(
            menu_helper,
            chat,
            chat.message_by_id(json_data["cmd_msg_id"]),
            video,
            send_helper,
            channels,
            tag_manager,
            json_data.get("manual_select", True),
        )
        menu.current_folder = json_data["current_folder"]
        return menu
