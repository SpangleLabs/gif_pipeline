from typing import TYPE_CHECKING

from telethon.tl.types import Message
import html

from gif_pipeline.database import Database
from gif_pipeline.helpers.public.public_helpers import PublicHelper
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient

if TYPE_CHECKING:
    from gif_pipeline.pipeline import Pipeline


class PublicTagHelper(PublicHelper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker, pipeline: "Pipeline"):
        super().__init__(database, client, worker)
        self.pipeline = pipeline

    async def on_new_message(self, message: Message):
        if message.forward and message.forward.channel_post:
            chat_id = message.forward.chat_id
            msg_id = message.forward.channel_post
            msg = self.pipeline.get_message_for_ids(chat_id, msg_id)
            if msg:
                tags = msg.tags(self.database)
                text = f"This post is from {html.escape(msg.chat_data.title)}."
                if tags:
                    text += " It has the following tags:\n"
                    tag_entries = []
                    for tag_key in sorted(tags.list_tag_names()):
                        tag_title = tag_key
                        if tag_key.endswith("__rejected"):
                            continue
                        if tag_title.endswith("__confirmed"):
                            tag_title = tag_key[:-len("__confirmed")]
                        tag_entries.append(f"<b>{html.escape(tag_title)}:</b> " + ", ".join(html.escape(t) for t in tags.list_values_for_tag(tag_key)))
                    text += "\n".join(tag_entries)
                else:
                    text += " It has no tags, sorry"
                await message.reply(text, parse_mode="html")
            else:
                await message.reply("I do not recognise this message")
            return
        await message.reply(
            "Hello there, please forward a gif from one of the channels at @spanglegifs to get the source link, "
            "and other tags."
        )
