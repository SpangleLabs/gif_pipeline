from typing import Optional, List

from gif_pipeline.chat import Chat
from gif_pipeline.database import Database
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.message import Message
from gif_pipeline.tag_manager import TagManager
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class TagHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker, tag_manager: TagManager):
        super().__init__(database, client, worker)
        self.tag_manager = tag_manager

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        clean_text = message.text.lower().strip()
        clean_args = clean_text.split()
        if clean_args[0] not in ["tag", "tags"]:
            return
        args = clean_args[1:]
        video = chat.message_by_id(message.message_data.reply_to)
        if video is None:
            link = next(iter(args), None)
            if link:
                video = self.tag_manager.get_message_for_link(link)
                args = args[1:]
        if not video:
            return [await self.send_text_reply(
                chat,
                message,
                "No message specified. Please reply to the message you want to view the tags for, or provide a "
                "link to it."
            )]
        tags = video.tags(self.database)
        text = "List of tags:\n"
        text += "\n".join(
            f"{key}: " + ", ".join(values)
            for key, values in tags.tags.items()
        )
        return [await self.send_text_reply(chat, message, text)]
