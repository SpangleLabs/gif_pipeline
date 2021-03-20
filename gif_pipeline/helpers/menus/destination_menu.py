from typing import List, Optional, TYPE_CHECKING

from telethon import Button

from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.menus.menu import Menu
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper


class DestinationMenu(Menu):
    confirm_send = "confirm_send"
    folder = "send_folder"

    def __init__(
            self,
            menu_helper: 'MenuHelper',
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            channels: List[Channel],
            current_folder: Optional[str]
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.channels = channels
        self.current_folder = current_folder

    @property
    def text(self) -> str:
        return "Which channel should this video be sent to?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
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
            callback_query: bytes
    ) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.confirm_send:
            destination_id = split_data[1]
            destination = self.send_helper.get_destination_from_name(destination_id)
            missing_tags = self.send_helper.missing_tags_for_video(self.video, destination)
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
            return await self.menu_helper.destination_menu(
                self.chat, self.cmd, self.video, self.send_helper, self.channels, folder
            )
