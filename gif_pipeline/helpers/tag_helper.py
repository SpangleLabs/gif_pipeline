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

    def is_priority(self, chat: Chat, message: Message) -> bool:
        clean_args = message.text.strip().split()
        if not clean_args or clean_args[0].lower() not in ["tag", "tags"]:
            return False
        return True

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        clean_args = message.text.strip().split()
        if not clean_args or clean_args[0].lower() not in ["tag", "tags"]:
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
        # Remove
        if args[0].lower() in ["remove", "delete", "unset"]:
            args = args[1:]
            # Remove all tags for a category
            if len(args) == 1:
                tag_name = args[0]
                tags = video.tags(self.database)
                if tag_name not in tags.tags:
                    text = f"This video has no tags for \"{tag_name}\"."
                else:
                    text = f"Removed all \"{tag_name}\" tags:\n"
                    text += "\n".join("- "+t for t in tags.tags[tag_name])
                    text += "\nFrom this video."
                    del tags.tags[tag_name]
                    self.database.save_tags(video.message_data, tags)
                return [await self.send_text_reply(chat, message, text)]
            # Remove a specific tag value
            tag_name = args[0]
            tag_value = " ".join(args[1:])
            tags = video.tags(self.database)
            if tag_name not in tags.tags:
                text = f"This video has no tags for \"{tag_name}\"."
            elif tag_value not in tags.tags[tag_name]:
                text = f"This video does not have a \"{tag_name}\" tag for \"{tag_value}\"."
            else:
                tags.tags[tag_name].remove(tag_value)
                text = f"Removed the \"{tag_name}\" tag for \"{tag_value}\" from this video."
                self.database.save_tags(video.message_data, tags)
            return [await self.send_text_reply(chat, message, text)]
        # Set/add a tag value
        tag_name = args[0]
        tag_value = " ".join(args[1:])
        tags = video.tags(self.database)
        tags.add_tag_value(tag_name, tag_value)
        self.database.save_tags(video.message_data, tags)
        text = f"Added \"{tag_name}\" tag: \"{tag_value}\"."
        return [await self.send_text_reply(chat, message, text)]
