from typing import List, Optional

from gif_pipeline.chat import Chat, WorkshopGroup
from gif_pipeline.database import Database
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.message import Message
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient
from gif_pipeline.video_tags import VideoTags


class ChannelFwdTagHelper(Helper):
    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        # Ignore messages which weren't forwarded from a public channel
        if message.message_data.forwarded_channel_link is None:
            return
        # Ignore messages which don't have a video
        if not message.has_video:
            return
        # Ignore channel messages
        if not isinstance(chat, WorkshopGroup):
            return
        self.usage_counter.inc()
        # Get tags
        tags = message.tags(self.database)
        tags.add_tag_value(VideoTags.source, message.message_data.forwarded_channel_link)
        # Save the tags
        self.database.save_tags(message.message_data, tags)
        # Say source tag was added
        return [
            await self.send_text_reply(
                chat, message, f"Added source tag: {message.message_data.forwarded_channel_link}"
            )
        ]
