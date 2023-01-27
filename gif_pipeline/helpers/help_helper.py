from typing import Optional, List, Tuple

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, find_video_for_message
from gif_pipeline.message import Message


class HelpHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker, menu_helper: MenuHelper):
        super().__init__(database, client, worker)
        self.menu_helper = menu_helper

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        clean_text = message.text.strip().lower()
        if clean_text == "help":
            return [await self.menu_helper.help_menu(chat, message, video, threshold, scene_list, self)]
