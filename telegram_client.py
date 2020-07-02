import logging
from asyncio import Future
from typing import Callable, Coroutine, Union, Generator, Optional, TypeVar, Any, List

import telethon
from telethon import events
from telethon.tl.custom import message
from telethon.tl.functions.messages import MigrateChatRequest

from group import ChatData, ChannelData, WorkshopData
from message import MessageData

R = TypeVar("R")


def message_data_from_telegram(msg: telethon.tl.custom.message.Message) -> MessageData:
    return MessageData(
            msg.chat.id,
            msg.id,
            msg.date,
            msg.text,
            msg.forward is not None,
            msg.file is not None,
            None,
            (msg.file or None) and msg.file.mime_type,
            msg.reply_to_msg_id,
            msg.sender.id,
            False
        )


def chat_id_from_telegram(msg: telethon.tl.custom.message.Message) -> int:
    return msg.chat.id if msg.chat is not None else msg.chat_id


class TelegramClient:
    def __init__(self, api_id: int, api_hash: str):
        self.client = telethon.TelegramClient('duplicate_checker', api_id, api_hash)
        self.client.start()
        self.message_cache = {}

    async def initialise(self) -> None:
        # Get dialogs list, to ensure entities are initialised in library
        await self.client.get_dialogs()

    def _save_message(self, msg: telethon.tl.custom.message.Message):
        # UpdateShortMessage events do not contain a populated msg.chat, so use msg.chat_id sometimes.
        chat_id = chat_id_from_telegram(msg)
        message_id = msg.id
        if chat_id not in self.message_cache:
            self.message_cache[chat_id] = {}
        self.message_cache[chat_id][message_id] = msg

    def _get_message(self, chat_id: int, message_id: int) -> Optional[telethon.tl.custom.message.Message]:
        if chat_id not in self.message_cache:
            return None
        return self.message_cache[chat_id].get(message_id)

    async def get_channel_data(self, handle: str) -> ChannelData:
        entity = await self.client.get_entity(handle)
        return ChannelData(entity.id, entity.username, entity.title)

    async def get_workshop_data(self, handle: str) -> WorkshopData:
        entity = await self.client.get_entity(handle)
        return WorkshopData(entity.id, entity.username, entity.title)

    async def iter_channel_messages(self, chat_data: ChatData) -> Generator[MessageData, None, None]:
        channel_handle = chat_data.username or chat_data.chat_id
        channel_entity = await self.client.get_entity(channel_handle)
        async for msg in self.client.iter_messages(channel_entity):
            # Skip edit photo events.
            if msg.action.__class__.__name__ in ['MessageActionChatEditPhoto']:
                continue
            # Save message and yield
            self._save_message(msg)
            yield message_data_from_telegram(msg)

    async def download_media(self, chat_id: int, message_id: int, path: str) -> Optional[str]:
        msg = self._get_message(chat_id, message_id)
        return await self.client.download_media(message=msg, file=path)

    def add_message_handler(self, function: Callable, chat_ids: List[int]) -> None:
        async def function_wrapper(event: events.NewMessage.Event):
            chat_id = chat_id_from_telegram(event.message)
            if chat_id not in chat_ids:
                logging.debug("Ignoring new message in other chat")
                return
            self._save_message(event.message)
            await function(event)

        self.client.add_event_handler(function_wrapper, events.NewMessage())
        self.client.add_event_handler(function_wrapper, events.MessageEdited())

    def add_delete_handler(self, function: Callable) -> None:
        async def function_wrapper(event: events.MessageDeleted.Event):
            await function(event)
            # We don't need to delete from cache, and trying to do so is tough without chat id

        self.client.add_event_handler(function_wrapper, events.MessageDeleted())

    async def send_text_message(
            self,
            chat_id: int,
            text: str,
            *,
            reply_to_msg_id: int = None
    ) -> telethon.tl.custom.message.Message:
        return await self.client.send_message(chat_id, text, reply_to=reply_to_msg_id)

    async def send_video_message(
            self, chat_id: int, video_path: str, text: str = None, *, reply_to_msg_id: int = None
    ) -> telethon.tl.custom.message.Message:
        return await self.client.send_file(
            chat_id, video_path, caption=text, reply_to=reply_to_msg_id, allow_cache=False
        )

    async def delete_message(self, message_data: MessageData) -> None:
        await self.client.delete_messages(message_data.chat_id, message_data.message_id)

    def synchronise_async(self, future: Union[Future, Coroutine]) -> Any:
        return self.client.loop.run_until_complete(future)

    async def upgrade_chat_to_supergroup(self, chat_id: int) -> None:
        await self.client(MigrateChatRequest(chat_id=chat_id))
