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
        # Get video
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
        # List all tags
        if not args:
            tags = video.tags(self.database)
            text = "List of tags:\n"
            text += "\n".join(
                f"{key}: " + ", ".join(values)
                for key, values in tags.tags.items()
            )
            return [await self.send_text_reply(chat, message, text)]
        # List tags for 1 category
        if len(args) == 1:
            tag_name = args[0]
            tags = video.tags(self.database)
            if tag_name not in tags.tags:
                text = f"This video has no tags for \"{tag_name}\"."
            else:
                text = f"List of \"{tag_name}\" tags:\n"
                text += "\n".join("- "+t for t in tags.tags[tag_name])
            return [await self.send_text_reply(chat, message, text)]
        # Set/add a tag value
        tag_name = args[0]
        tag_value = " ".join(args[1:])
        tags = video.tags(self.database)
        tags.add_tag_value(tag_name, tag_value)
        self.database.save_tags(video.message_data, tags)
        text = f"Added \"{tag_name}\" tag: \"{tag_value}\"."
        return [await self.send_text_reply(chat, message, text)]

