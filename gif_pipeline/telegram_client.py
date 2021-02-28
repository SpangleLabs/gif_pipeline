import logging
from asyncio import Future
from typing import Callable, Coroutine, Union, Generator, Optional, TypeVar, Any, List

import telethon
from telethon import events, Button
from telethon.tl.custom import message
from telethon.tl.functions.channels import EditAdminRequest
from telethon.tl.functions.messages import MigrateChatRequest, GetScheduledHistoryRequest
from telethon.tl.types import ChatAdminRights, ChannelParticipantsAdmins, ChannelParticipantCreator

from gif_pipeline.group import ChatData, ChannelData, WorkshopData
from gif_pipeline.message import MessageData

R = TypeVar("R")


def message_data_from_telegram(msg: telethon.tl.custom.message.Message, scheduled: bool = False) -> MessageData:
    chat_id = chat_id_from_telegram(msg)
    sender_id = sender_id_from_telegram(msg)
    return MessageData(
        chat_id,
        msg.id,
        msg.date,
        msg.text,
        msg.forward is not None,
        msg.file is not None,
        None,
        (msg.file or None) and msg.file.mime_type,
        msg.reply_to_msg_id,
        sender_id,
        scheduled
    )


def chat_id_from_telegram(msg: telethon.tl.custom.message.Message) -> int:
    return msg.chat_id


def sender_id_from_telegram(msg: telethon.tl.custom.message.Message) -> int:
    return msg.sender_id


class TelegramClient:
    def __init__(self, api_id: int, api_hash: str, pipeline_bot_token: str = None, public_bot_token: str = None):
        self.client = telethon.TelegramClient('duplicate_checker', api_id, api_hash)
        self.client.start()
        self.pipeline_bot_id = None
        self.pipeline_bot_client = self.client
        if pipeline_bot_token:
            self.pipeline_bot_client = telethon.TelegramClient("duplicate_checker_pipeline_bot", api_id, api_hash)
            self.pipeline_bot_client.start(bot_token=pipeline_bot_token)
        self.public_bot_client = self.client
        if public_bot_token:
            self.public_bot_client = telethon.TelegramClient('duplicate_checker_public_bot', api_id, api_hash)
            self.public_bot_client.start(bot_token=public_bot_token)
        self.message_cache = {}

    async def initialise(self) -> None:
        # Get dialogs list, to ensure entities are initialised in library
        await self.client.get_dialogs()
        pipeline_bot_user = await self.pipeline_bot_client.get_me()
        self.pipeline_bot_id = pipeline_bot_user.id

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
        peer_id = telethon.utils.get_peer_id(entity)
        return ChannelData(peer_id, entity.username, entity.title)

    async def get_workshop_data(self, handle: str) -> WorkshopData:
        entity = await self.client.get_entity(handle)
        peer_id = telethon.utils.get_peer_id(entity)
        return WorkshopData(peer_id, entity.username, entity.title)

    async def iter_channel_messages(
            self,
            chat_data: ChatData,
            and_scheduled: bool = True
    ) -> Generator[MessageData, None, None]:
        async for msg in self.client.iter_messages(chat_data.chat_id):
            # Skip edit photo events.
            if msg.action.__class__.__name__ in ['MessageActionChatEditPhoto']:
                continue
            # Save message and yield
            self._save_message(msg)
            yield message_data_from_telegram(msg)
        if and_scheduled:
            async for msg_data in self.iter_scheduled_channel_messages(chat_data):
                yield msg_data

    async def iter_scheduled_channel_messages(self, chat_data: ChatData) -> Generator[MessageData, None, None]:
        # noinspection PyTypeChecker
        messages = await self.client(GetScheduledHistoryRequest(
            peer=chat_data.chat_id,
            hash=0
        ))
        for msg in messages.messages:
            self._save_message(msg)
            yield message_data_from_telegram(msg, scheduled=True)

    async def download_media(self, chat_id: int, message_id: int, path: str) -> Optional[str]:
        msg = self._get_message(chat_id, message_id)
        return await self.client.download_media(message=msg, file=path)

    def add_message_handler(self, function: Callable, chat_ids: List[int]) -> None:
        async def function_wrapper(event: events.NewMessage.Event):
            chat_id = chat_id_from_telegram(event.message)
            if chat_id not in chat_ids:
                logging.debug("Ignoring new message in other chat")
                return
            sender_id = sender_id_from_telegram(event.message)
            if sender_id == self.pipeline_bot_id:
                logging.debug("Ignoring new message from bot")
                return
            self._save_message(event.message)
            await function(event)

        self.client.add_event_handler(function_wrapper, events.NewMessage())

    def add_edit_handler(self, function: Callable, chat_ids: List[int]) -> None:
        async def function_wrapper(event: events.NewMessage.Event):
            chat_id = chat_id_from_telegram(event.message)
            if chat_id not in chat_ids:
                logging.debug("Ignoring new message in other chat")
                return
            sender_id = sender_id_from_telegram(event.message)
            if sender_id == self.pipeline_bot_id:
                logging.debug("Ignoring new message from bot")
                return
            self._save_message(event.message)
            await function(event)

        self.client.add_event_handler(function_wrapper, events.MessageEdited())

    def add_delete_handler(self, function: Callable) -> None:
        async def function_wrapper(event: events.MessageDeleted.Event):
            await function(event)
            # We don't need to delete from cache, and trying to do so is tough without chat id

        self.pipeline_bot_client.add_event_handler(function_wrapper, events.MessageDeleted())

    def add_callback_query_handler(self, function: Callable) -> None:
        async def function_wrapper(event: events.CallbackQuery.Event):
            await function(event)

        self.pipeline_bot_client.add_event_handler(function_wrapper, events.CallbackQuery())

    async def send_text_message(
            self,
            chat: ChatData,
            text: str,
            *,
            reply_to_msg_id: Optional[int] = None,
            buttons: Optional[List[List[Button]]] = None
    ) -> telethon.tl.custom.message.Message:
        return await self.pipeline_bot_client.send_message(chat.chat_id, text, reply_to=reply_to_msg_id,
                                                           buttons=buttons)

    async def send_video_message(
            self,
            chat: ChatData,
            video_path: str,
            text: str = None,
            *,
            reply_to_msg_id: int = None,
            buttons: Optional[List[List[Button]]] = None
    ) -> telethon.tl.custom.message.Message:
        return await self.pipeline_bot_client.send_file(
            chat.chat_id, video_path, caption=text, reply_to=reply_to_msg_id, allow_cache=False, buttons=buttons
        )

    async def delete_message(self, message_data: MessageData) -> None:
        await self.client.delete_messages(message_data.chat_id, message_data.message_id)

    async def forward_message(self, chat: ChatData, message_data: MessageData) -> telethon.tl.custom.message.Message:
        return await self.pipeline_bot_client.forward_messages(
            chat.chat_id,
            message_data.message_id,
            message_data.chat_id
        )

    async def edit_message(
            self,
            chat: ChatData,
            message_data: MessageData,
            new_text: str,
            new_buttons: Optional[List[List[Button]]] = None
    ):
        return await self.pipeline_bot_client.edit_message(
            chat.chat_id,
            message_data.message_id,
            new_text,
            buttons=new_buttons
        )

    def synchronise_async(self, future: Union[Future, Coroutine]) -> Any:
        return self.client.loop.run_until_complete(future)

    async def upgrade_chat_to_supergroup(self, chat_id: int) -> None:
        await self.client(MigrateChatRequest(chat_id=chat_id))

    async def invite_pipeline_bot_to_chat(self, chat_data: ChatData) -> None:
        if self.pipeline_bot_client == self.client:
            return
        users = await self.client.get_participants(chat_data.chat_id)
        user_ids = [user.id for user in users if user.username is not None]
        if self.pipeline_bot_id in user_ids:
            return
        pipeline_bot_entity = await self.pipeline_bot_client.get_me()
        await self.client(EditAdminRequest(
            chat_data.chat_id,
            pipeline_bot_entity.username,
            ChatAdminRights(
                post_messages=True,
                edit_messages=True,
                delete_messages=True
            ),
            "Helpful bot"
        ))

    async def list_authorized_channel_posters(self, chat_data: ChatData) -> List[int]:
        allowed_ids = []
        async for admin in self.client.iter_participants(chat_data.chat_id, filter=ChannelParticipantsAdmins()):
            if isinstance(admin.participant, ChannelParticipantCreator) or admin.participant.admin_rights.post_messages:
                allowed_ids.append(admin.id)
        return allowed_ids

    async def list_authorized_to_delete(self, chat_data: ChatData) -> List[int]:
        allowed_ids = []
        async for admin in self.client.iter_participants(chat_data.chat_id, filter=ChannelParticipantsAdmins()):
            if (
                    isinstance(admin.participant, ChannelParticipantCreator)
                    or admin.participant.admin_rights.delete_messages
            ):
                allowed_ids.append(admin.id)
        return allowed_ids
