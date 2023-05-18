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
        if not await self.client.user_can_delete_in_chat(message.message_data.sender_id, chat.chat_data):
            return None
        if text_clean == "delete family":
            if message.message_data.reply_to is None:
                error_text = "You need to reply to the message you want to delete."
                return [await self.send_text_reply(chat, message, error_text)]
            return await self.delete_family(chat, message)
        if text_clean == "delete branch":
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
        await self.delete_msgs(chat, message_family)
        return []

    async def delete_msgs(self, chat: Chat, msg_data: List[MessageData]) -> None:
        copies = [chat.message_by_id(msg.message_id) for msg in msg_data]
        await self.client.delete_messages(msg_data)
        for msg, copy in zip(msg_data, copies):
            copy.delete(self.database)
            chat.remove_message(msg)
            self.menu_cache.remove_menu_by_message(copy)

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
        if not await self.client.user_can_delete_in_chat(sender_id, menu.msg.chat_data):
            return None
        message_id = int(query_split[1])
        message = menu.menu.chat.message_by_id(message_id)
        resp = await self.delete_family(menu.menu.chat, message)
        return resp

    async def on_stateless_callback(
            self,
            callback_query: bytes,
            chat: Chat,
            message: Message,
            sender_id: int,
    ) -> Optional[List[Message]]:
        if callback_query.decode() != "delete_me":
            return None
        resp = await self.delete_msg(chat, message.message_data)
        return resp
