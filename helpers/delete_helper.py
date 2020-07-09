from typing import Optional, List

from database import Database
from group import Group
from helpers.helpers import Helper
from message import Message
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient


class DeleteHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        # If a message says to delete, delete it and delete local files
        text_clean = message.text.strip().lower()
        if text_clean != "delete family":
            return None
        message_history = self.database.get_message_history(message.message_data)
        if len(message_history) == 1:
            return [await self.send_text_reply(chat, message, "I'm not sure which message you want to delete.")]
        message_family = self.database.get_message_family(message_history[-1])
        for msg_data in message_family:
            msg = chat.message_by_id(msg_data.message_id)
            await self.client.delete_message(msg_data)
            msg.delete(self.database)
        return []

    async def on_callback_query(self, chat: Group, callback_query: bytes) -> Optional[List[Message]]:
        query_split = callback_query.decode().split(":")
        if query_split[0] != "delete":
            return None
        message_id = int(query_split[1])
        message = chat.message_by_id(message_id)
        message_history = self.database.get_message_history(message.message_data)
        message_family = self.database.get_message_family(message_history[-1])
        for msg_data in message_family:
            msg = chat.message_by_id(msg_data.message_id)
            await self.client.delete_message(msg_data)
            msg.delete(self.database)
        return []