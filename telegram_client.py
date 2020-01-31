from asyncio import Future
from typing import Callable, Coroutine, Union

import telethon
from telethon import events
from telethon.tl.custom import message


class TelegramClient:
    def __init__(self, api_id, api_hash):
        self.client = telethon.TelegramClient('duplicate_checker', api_id, api_hash)
        self.client.start()
        self.message_cache = {}

    async def initialise(self):
        # Get dialogs list, to ensure entities are initialised in library
        await self.client.get_dialogs()

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
        self.client.add_event_handler(function_wrapper, events.MessageEdited())

    def add_delete_handler(self, function: Callable):
        async def function_wrapper(event: events.MessageDeleted.Event):
            await function(event)
            # We don't need to delete from cache, and trying to do so is tough without chat id
        self.client.add_event_handler(function_wrapper, events.MessageDeleted())

    async def send_text_message(self, chat_id: int, text: str, *, reply_to_msg_id: int = None) -> message.Message:
        return await self.client.send_message(chat_id, text, reply_to=reply_to_msg_id)

    async def send_video_message(
            self, chat_id: int, video_path: str, text: str = None, *, reply_to_msg_id: int = None
    ) -> message.Message:
        return await self.client.send_file(
            chat_id, video_path, caption=text, reply_to=reply_to_msg_id, allow_cache=False
        )

    async def delete_message(self, chat_id: int, message_id: int):
        await self.client.delete_messages(chat_id, message_id)

    def synchronise_async(self, future: Union[Future, Coroutine]):
        return self.client.loop.run_until_complete(future)
