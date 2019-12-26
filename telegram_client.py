from typing import Callable

import telethon
from telethon import events


class TelegramClient:
    def __init__(self, api_id, api_hash):
        self.client = telethon.TelegramClient('duplicate_checker', api_id, api_hash)
        self.client.start()
        self.message_cache = {}

    def _save_message(self, message):
        chat_id = message.chat_id
        message_id = message.id
        if chat_id not in self.message_cache:
            self.message_cache[chat_id] = {}
        self.message_cache[chat_id][message_id] = message

    def _get_message(self, chat_id: int, message_id: int):
        if chat_id not in self.message_cache:
            return None
        return self.message_cache[chat_id].get(message_id)

    async def iter_channel_messages(self, channel_handle: str):
        channel_entity = await self.client.get_entity(channel_handle)
        async for message in self.client.iter_messages(channel_entity):
            self._save_message(message)
            yield message

    async def download_media(self, chat_id: int, message_id: int, path: str):
        message = self._get_message(chat_id, message_id)
        return await self.client.download_media(message=message, file=path)

    def add_message_handler(self, function: Callable):
        async def function_wrapper(event: events.NewMessage.Event):
            self._save_message(event.message)
            await function(event)
        self.client.add_event_handler(function_wrapper, events.NewMessage())
