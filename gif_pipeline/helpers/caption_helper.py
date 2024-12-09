import logging
from typing import Optional, List

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, find_video_for_message
from gif_pipeline.message import Message

logger = logging.getLogger(__name__)

class CaptionHelper(Helper):

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        clean_msg = message.text.strip()
        if clean_msg[:7].lower() != "caption":
            return None
        caption = message.text[7:].strip()
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(
                chat,
                message,
                "I am not sure which video you would like to add a message caption to. Please reply to the video."
            )]
        tags = video.tags(self.database)
        return [await self.send_video_reply(chat, message, video.message_data.file_path, tags, caption)]
