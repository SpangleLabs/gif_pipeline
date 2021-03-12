from typing import Optional, List

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.message import Message


class TagHelper(Helper):

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        clean_text = message.text.lower().strip()
        if not clean_text.startswith("tag"):
            return
        args = clean_text[len("tag"):].strip()
        video = self.get_video(chat, message, args)
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

    def get_video(self, chat: Chat, message: Message, args: str) -> Optional[Message]:
        reply_to = chat.message_by_id(message.message_data.reply_to)
        if reply_to is not None:
            return reply_to
        link = next(iter(args.split()), None)
        if link:
            return chat.message_by_link(link)
        return None
