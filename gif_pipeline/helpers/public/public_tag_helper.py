from telethon import events
from telethon.tl.types import Message

from gif_pipeline.database import Database
from gif_pipeline.helpers.public.public_helpers import PublicHelper
from gif_pipeline.tag_manager import TagManager
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class PublicTagHelper(PublicHelper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker, tag_manager: TagManager):
        super().__init__(database, client, worker)
        self.tag_manager = tag_manager

    async def on_new_message(self, message: Message):
        if message.forward and message.forward.channel_post:
            chat_id = message.forward.channel_id
            msg_id = message.forward.channel_post
            msg = self.tag_manager.get_message_for_ids(chat_id, msg_id)
            if msg:
                tags = msg.tags(self.database)
                text = f"This post is from {msg.chat_data.title}."
                if tags:
                    text += " It has the following tags:\n"
                    for tag_key, tag_values in tags.tags.items():
                        text += f"{tag_key}: " + ", ".join(tag_values)
                else:
                    text += " It has no tags, sorry"
                await message.reply(text)
            else:
                await message.reply("I do not recognise this message")
            return
        await message.reply(
            "Hello there, please forward a gif from one of the channels at @spanglegifs to get the source link, "
            "and other tags."
        )
