from typing import List, Tuple, Optional, TYPE_CHECKING

from scenedetect import FrameTimecode
from telethon import Button

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.menus.menu import Menu
from gif_pipeline.helpers.scene_split_helper import SceneSplitHelper
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper


class SplitScenesConfirmationMenu(Menu):
    cmd_split = b"split"
    cmd_cancel = b"split_clear_menu"

    def __init__(
            self,
            menu_helper: 'MenuHelper',
            chat: Chat,
            cmd: Message,
            video: Message,
            threshold: int,
            scene_list: List[Tuple[FrameTimecode, FrameTimecode]],
            split_helper: SceneSplitHelper
    ):
        super().__init__(menu_helper, chat, cmd, video)
        self.threshold = threshold
        self.scene_list = scene_list
        self.split_helper = split_helper
        self.cleared = False

    @property
    def text(self) -> str:
        scene_count = len(self.scene_list)
        if not self.cleared:
            return f"Using a threshold of {self.threshold}, this video would be split into {scene_count} scenes. " \
               f"Would you like to proceed with cutting?"
        return f"Using a threshold of {self.threshold}, this video would have been split into {scene_count} scenes."

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        if not self.cleared:
            return [
                [Button.inline("Yes please", self.cmd_split)],
                [Button.inline("No thank you", self.cmd_cancel)]
            ]

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.cmd_cancel:
            self.cleared = True
            sent_msg = await self.send()
            return [sent_msg]
        if callback_query == self.cmd_split:
            await self.delete()
            progress_text = f"Splitting video into {len(self.scene_list)} scenes"
            async with self.menu_helper.progress_message(self.chat, self.cmd, progress_text):
                return await self.split_helper.split_scenes(self.chat, self.cmd, self.video, self.scene_list)
