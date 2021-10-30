from typing import Optional, List

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.menu_cache import SentMenu, MenuCache
from gif_pipeline.message import Message, MessageData
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class DeleteHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker, menu_cache: 'MenuCache'):
        super().__init__(database, client, worker)
        self.menu_cache = menu_cache

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        # If a message says to delete, delete it and delete local files
        text_clean = message.text.strip().lower()
        if not text_clean.startswith("delete"):
            return None
        self.usage_counter.inc()
        admin_ids = await self.client.list_authorized_to_delete(chat.chat_data)
        if text_clean == "delete family":
            if message.message_data.sender_id not in admin_ids:
                return None
            if message.message_data.reply_to is None:
                error_text = "You need to reply to the message you want to delete."
                return [await self.send_text_reply(chat, message, error_text)]
            return await self.delete_family(chat, message)
        if text_clean == "delete branch":
            if message.message_data.sender_id not in admin_ids:
                return None
            if message.message_data.reply_to is None:
                error_text = "You need to reply to the message you want to delete."
                return [await self.send_text_reply(chat, message, error_text)]
            reply_to = chat.message_by_id(message.message_data.reply_to)
            return await self.delete_branch(chat, reply_to.message_data)
        return None

    async def delete_family(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        message_history = self.database.get_message_history(message.message_data)
        return await self.delete_branch(chat, message_history[-1])

    async def delete_branch(self, chat: Chat, message: MessageData) -> Optional[List[Message]]:
        message_family = self.database.get_message_family(message)
        for msg_data in message_family:
            await self.delete_msg(chat, msg_data)
        return []

    async def delete_msg(self, chat: Chat, msg_data: MessageData) -> None:
        msg = chat.message_by_id(msg_data.message_id)
        await self.client.delete_message(msg_data)
        msg.delete(self.database)
        chat.remove_message(msg_data)
        self.menu_cache.remove_menu_by_message(msg)

    async def on_callback_query(
            self,
            callback_query: bytes,
            menu: SentMenu,
            sender_id: int,
    ) -> Optional[List[Message]]:
        query_split = callback_query.decode().split(":")
        if query_split[0] != "delete":
            return None
        admin_ids = await self.client.list_authorized_to_delete(menu.msg.chat_data)
        if sender_id not in admin_ids:
            return None
        message_id = int(query_split[1])
        message = menu.menu.chat.message_by_id(message_id)
        resp = await self.delete_family(menu.menu.chat, message)
        return resp
