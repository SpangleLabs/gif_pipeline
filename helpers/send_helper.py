import asyncio
import shutil
from abc import abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, List, Union

from telethon import Button

from database import Database
from group import Group, Channel
from helpers.helpers import Helper, find_video_for_message
from menu_cache import MenuOwnershipCache
from message import Message
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient, message_data_from_telegram


class GifSendHelper(Helper):

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            channels: List[Channel],
            menu_ownership_cache: MenuOwnershipCache
    ):
        super().__init__(database, client, worker)
        self.channels = channels

        self.menu_helper = MenuHelper(self, menu_ownership_cache)

    @property
    def writable_channels(self) -> List[Channel]:
        return [channel for channel in self.channels if not channel.config.read_only]

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        # If a message says to send to a channel, and replies to a gif, then forward to that channel
        # `send deergifs`, `send cowgifs->deergifs`
        # Needs to handle queueing too?
        text_clean = message.text.lower().strip()
        if not text_clean.startswith("send"):
            return
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "I'm not sure which gif you want to send.")]
        # Clean up any menus for that message which already exist
        await self.menu_helper.delete_menu_for_video(video)
        # Read dest string
        dest_str = text_clean[4:].strip()
        if not was_giffed(self.database, video):
            return await self.menu_helper.send_not_gif_warning_menu(chat, message, video, dest_str)
        return await self.handle_dest_str(chat, message, video, dest_str, message.message_data.sender_id)

    async def on_callback_query(self, chat: Group, callback_query: bytes, sender_id: int) -> Optional[List[Message]]:
        menu_handler_resp = await self.menu_helper.on_callback_query(chat, callback_query, sender_id)
        if menu_handler_resp is not None:
            return menu_handler_resp

    async def handle_dest_str(
            self,
            chat: Group,
            cmd: Message,
            video: Message,
            dest_str: str,
            sender_id: int
    ) -> List[Message]:
        if dest_str == "":
            return await self.menu_helper.destination_menu(chat, cmd, video, sender_id)
        if "<->" in dest_str:
            destinations = dest_str.split("<->", 1)
            return await self.send_two_way_forward(chat, cmd, video, destinations[0], destinations[1], sender_id)
        if "->" in dest_str:
            destinations = dest_str.split("->", 1)
            return await self.send_forward(chat, cmd, video, destinations[0], destinations[1], sender_id)
        if "<-" in dest_str:
            destinations = dest_str.split("<-", 1)
            return await self.send_forward(chat, cmd, video, destinations[1], destinations[0], sender_id)
        return await self.send_video(chat, video, dest_str, sender_id)

    async def send_two_way_forward(
            self,
            chat: Group,
            cmd_message: Message,
            video: Message,
            destination1: str,
            destination2: str,
            sender_id: int
    ) -> List[Message]:
        messages = []
        messages += await self.send_forward(chat, cmd_message, video, destination1, destination2, sender_id),
        messages += await self.send_forward(chat, cmd_message, video, destination2, destination1, sender_id)
        return messages

    async def send_forward(
            self,
            chat: Group,
            cmd_message: Message,
            video: Message,
            destination_from: str,
            destination_to: str,
            sender_id: int
    ) -> List[Message]:
        chat_from = self.get_destination_from_name(destination_from)
        if chat_from is None:
            return [await self.send_text_reply(chat, cmd_message, f"Unrecognised destination from: {destination_from}")]
        chat_to = self.get_destination_from_name(destination_to)
        if chat_to is None:
            return [await self.send_text_reply(chat, cmd_message, f"Unrecognised destination to: {destination_to}")]
        # Check permissions in both groups
        from_admin_ids = await self.client.list_authorized_channel_posters(chat_from.chat_data)
        to_admin_ids = await self.client.list_authorized_channel_posters(chat_to.chat_data)
        if sender_id not in from_admin_ids or sender_id not in to_admin_ids:
            error_text = f"You need to be an admin of both channels to send a forwarded video."
            return [await self.send_text_reply(chat, cmd_message, error_text)]
        # Send initial message
        initial_message = await self.send_message(chat_from, video_path=video.message_data.file_path)
        # Forward message
        new_message = await self.forward_message(chat_to, initial_message)
        # Delete initial message
        await self.client.delete_message(initial_message.message_data)
        initial_message.delete(self.database)
        confirm_text = f"This gif has been sent to {chat_to.chat_data.title} via {chat_from.chat_data.title}"
        confirm_message = await self.menu_helper.after_send_delete_menu(chat, video, confirm_text, sender_id)
        messages = [new_message]
        if confirm_message:
            messages.append(confirm_message)
        return messages

    async def send_video(
            self,
            chat: Group,
            video: Message,
            destination_id: Union[str, int],
            sender_id: int
    ) -> List[Message]:
        destination = self.get_destination_from_name(destination_id)
        if destination is None:
            return [await self.send_text_reply(chat, video, f"Unrecognised destination: {destination_id}")]
        dest_admin_ids = await self.client.list_authorized_channel_posters(destination.chat_data)
        if sender_id not in dest_admin_ids:
            return [await self.send_text_reply(chat, video, "You do not have permission to post in that channel.")]
        new_message = await self.send_message(destination, video_path=video.message_data.file_path)
        confirm_text = f"This gif has been sent to {destination.chat_data.title}."
        confirm_message = await self.menu_helper.after_send_delete_menu(chat, video, confirm_text, sender_id)
        messages = [new_message]
        if confirm_message:
            messages.append(confirm_message)
        return messages

    def get_destination_from_name(self, destination_id: Union[str, int]) -> Optional[Group]:
        destination = None
        for channel in self.writable_channels:
            if channel.chat_data.username == destination_id:
                destination = channel
                break
            if str(channel.chat_data.chat_id) == str(destination_id):
                destination = channel
                break
        return destination

    async def forward_message(self, destination: Group, message: Message) -> Message:
        msg = await self.client.forward_message(destination.chat_data, message.message_data)
        message_data = message_data_from_telegram(msg)
        if message.has_video:
            # Copy file
            new_path = message_data.expected_file_path(destination.chat_data)
            shutil.copyfile(message.message_data.file_path, new_path)
            message_data.file_path = new_path
        # Set up message object
        new_message = await Message.from_message_data(message_data, destination.chat_data, self.client)
        self.database.save_message(new_message.message_data)
        destination.add_message(new_message)
        return new_message


class MenuHelper:
    def __init__(self, send_helper: GifSendHelper, menu_ownership_cache: MenuOwnershipCache):
        # Cache of message ID the menu is replying to, to the menu
        self.send_helper = send_helper
        self.menu_cache = defaultdict(lambda: {})
        # TODO: eventually remove this class, when MenuHelper is handling all menus
        self.menu_ownership_cache = menu_ownership_cache

    def add_menu_to_cache(self, sent_menu: 'SentMenu') -> None:
        self.menu_cache[
            sent_menu.menu.video.chat_data.chat_id
        ][
            sent_menu.menu.video.message_data.message_id
        ] = sent_menu
        self.menu_ownership_cache.add_menu_msg(sent_menu.msg, sent_menu.menu.owner_id)

    def get_menu_from_cache(self, video: Message) -> Optional['SentMenu']:
        return self.menu_cache.get(video.chat_data.chat_id, {}).get(video.message_data.message_id)

    async def delete_menu_for_video(self, video: Message) -> None:
        menu = self.get_menu_from_cache(video)
        if menu:
            await self.send_helper.client.delete_message(menu.msg.message_data)
            menu.msg.delete(self.send_helper.database)
            self.remove_menu_from_cache(video)

    def remove_menu_from_cache(self, video: Message) -> None:
        menu = self.get_menu_from_cache(video)
        if menu:
            del self.menu_cache[video.chat_data.chat_id][video.message_data.message_id]
            self.menu_ownership_cache.remove_menu_msg(menu.msg)

    async def on_callback_query(self, chat: Group, callback_query: bytes, sender_id: int) -> Optional[List[Message]]:
        menus = [
            menu
            for video_msg_id, menu in self.menu_cache.get(chat.chat_data.chat_id, {}).items()
            if menu.owner_id == sender_id
        ]
        for menu in menus:
            resp = await menu.handle_callback_query(chat, callback_query, sender_id)
            if resp:
                return resp

    async def send_not_gif_warning_menu(
            self,
            chat: Group,
            cmd: Message,
            video: Message,
            dest_str: str
    ) -> List[Message]:
        sender_id = cmd.message_data.sender_id
        menu = NotGifConfirmationMenu(self, chat, video, sender_id, dest_str)
        menu_msg = await menu.send()
        return [menu_msg]

    async def destination_menu(self, chat: Group, cmd: Message, video: Message, sender_id: int) -> List[Message]:
        channels = await self.available_channels_for_user(sender_id)
        if not channels:
            return [
                await self.send_helper.send_text_reply(
                    chat,
                    cmd,
                    "You do not have permission to send to any available channels."
                )
            ]
        menu = DestinationMenu(self, chat, video, sender_id, channels)
        menu_msg = await menu.send()
        return [menu_msg]

    async def available_channels_for_user(self, user_id: int) -> List[Channel]:
        all_channels = self.send_helper.writable_channels
        user_is_admin = asyncio.gather(*(self.user_admin_in_channel(user_id, channel) for channel in all_channels))
        return [
            channel for channel, is_admin in zip(all_channels, user_is_admin) if is_admin
        ]

    async def user_admin_in_channel(self, user_id: int, channel: Channel) -> bool:
        admin_ids = await self.send_helper.client.list_authorized_channel_posters(channel.chat_data)
        return user_id in admin_ids

    async def confirmation_menu(self, chat: Group, video_id: str, destination_id: str, sender_id: int) -> List[Message]:
        destination = self.send_helper.get_destination_from_name(destination_id)
        video = chat.message_by_id(int(video_id))
        menu = SendConfirmationMenu(self, chat, video, sender_id, destination)
        menu_msg = await menu.send()
        return [menu_msg]

    async def after_send_delete_menu(
            self,
            chat: Group,
            video: Message,
            text: str,
            sender_id: int
    ) -> Optional[Message]:
        admin_ids = await self.send_helper.client.list_authorized_to_delete(chat.chat_data)
        if sender_id not in admin_ids:
            await self.delete_menu_for_video(video)
            return None
        menu = DeleteMenu(self, chat, video, sender_id, text)
        message = await menu.send()
        return message


@dataclass
class SentMenu:
    menu: 'Menu'
    msg: Message


class Menu:

    def __init__(self, menu_helper: MenuHelper, chat: Group, video: Message, owner_id: int):
        self.menu_helper = menu_helper
        self.chat = chat
        self.video = video
        self.owner_id = owner_id

    def add_self_to_cache(self, menu_msg: Message):
        self.menu_helper.add_menu_to_cache(SentMenu(self, menu_msg))

    @property
    @abstractmethod
    def text(self) -> str:
        pass

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return None

    async def handle_callback_query(
            self,
            chat: Group,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        pass

    async def send_as_reply(self, reply_to: Message) -> Message:
        menu_msg = await self.menu_helper.send_helper.send_text_reply(
            self.chat,
            reply_to,
            self.text,
            buttons=self.buttons
        )
        self.add_self_to_cache(menu_msg)
        return menu_msg

    async def edit_message(self, old_msg: Message) -> Message:
        menu_msg = await self.menu_helper.send_helper.edit_message(
            self.chat,
            old_msg,
            new_text=self.text,
            new_buttons=self.buttons
        )
        if self.buttons:
            self.add_self_to_cache(menu_msg)
        else:
            self.menu_helper.remove_menu_from_cache(self.video)
        return menu_msg

    async def send(self) -> Message:
        menu = self.menu_helper.get_menu_from_cache(self.video)
        if menu:
            return await self.edit_message(menu.msg)
        return await self.send_as_reply(self.video)

    async def delete(self) -> None:
        await self.menu_helper.delete_menu_for_video(self.video)


class NotGifConfirmationMenu(Menu):
    clear_menu = b"clear_not_gif_menu"
    send_str = "send_str"

    def __init__(
            self, menu_helper: MenuHelper, chat: Group, video: Message, sender_id: int, cmd_msg: Message, dest_str: str
    ):
        super().__init__(menu_helper, chat, video, sender_id)
        self.cmd_msg = cmd_msg
        self.dest_str = dest_str

    @property
    def text(self) -> str:
        return "It looks like this video has not been giffed. Are you sure you want to send it?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        video_id = self.video.message_data.message_id
        cmd_id = self.cmd_msg.message_data.message_id
        button_data = f"{self.send_str}:{video_id}:{cmd_id}:{self.dest_str}"
        return [
            [Button.inline("Yes, I am sure", button_data)],
            [Button.inline("No thanks!", self.clear_menu)]
        ]

    async def handle_callback_query(
            self,
            chat: Group,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        if callback_query == self.clear_menu:
            await self.delete()
            return []
        # Handle sending if the user is sure
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.send_str:
            _, video_id, cmd_id, dest_str = split_data
            video_msg = chat.message_by_id(int(video_id))
            cmd_message = chat.message_by_id(int(cmd_id))
            return await self.menu_helper.send_helper.handle_dest_str(
                chat, cmd_message, video_msg, dest_str, sender_id
            )


class DestinationMenu(Menu):
    confirm_send = "confirm_send"

    def __init__(self, menu_helper: MenuHelper, chat: Group, video: Message, owner_id: int, channels: List[Channel]):
        super().__init__(menu_helper, chat, video, owner_id)
        self.channels = channels

    @property
    def text(self) -> str:
        return "Which channel should this video be sent to?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        video_message_id = self.video.message_data.message_id
        return [
            [Button.inline(
                channel.chat_data.title,
                f"{self.confirm_send}:{video_message_id}:{channel.chat_data.chat_id}"
            )]
            for channel in self.channels
        ]

    async def handle_callback_query(
            self,
            chat: Group,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.confirm_send:
            video_id = split_data[1]
            destination_id = split_data[2]
            return await self.menu_helper.confirmation_menu(chat, video_id, destination_id, sender_id)


class SendConfirmationMenu(Menu):
    clear_confirm_menu = b"clear_menu"
    send_callback = "send"

    def __init__(self, menu_helper: MenuHelper, chat: Group, video: Message, owner_id: int, destination: Group):
        super().__init__(menu_helper, chat, video, owner_id)
        self.destination = destination

    @property
    def text(self) -> str:
        return f"Are you sure you want to send this video to {self.destination.chat_data.title}?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        button_data = f"{self.send_callback}:{self.video.message_data.message_id}:{self.destination.chat_data.chat_id}"
        return [
            [Button.inline("I am sure", button_data)],
            [Button.inline("No thanks", self.clear_confirm_menu)]
        ]

    async def handle_callback_query(
            self,
            chat: Group,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        if callback_query == self.clear_confirm_menu:
            await self.delete()
            return []
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.send_callback:
            destination_id = split_data[2]
            message = chat.message_by_id(int(split_data[1]))
            return await self.menu_helper.send_helper.send_video(chat, message, destination_id, sender_id)


class DeleteMenu(Menu):
    def __init__(self, menu_helper: MenuHelper, chat: Group, video: Message, owner_id: int, prefix_str: str):
        super().__init__(menu_helper, chat, video, owner_id)
        self.prefix_str = prefix_str
        self.cleared = False

    @property
    def text(self):
        if self.cleared:
            return self.prefix_str
        return self.prefix_str + "\nWould you like to delete the message family?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        if self.cleared:
            return None
        return [
            [Button.inline("Yes please", f"delete:{self.video.message_data.message_id}")],
            [Button.inline("No thanks", f"clear_delete_menu")]
        ]

    async def handle_callback_query(
            self,
            chat: Group,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == "clear_delete_menu":
            self.cleared = True
            sent_msg = await self.send()
            return [sent_msg]
        # The "delete:" callback is handled by DeleteHelper


def was_giffed(database: Database, video: Message) -> bool:
    message_history = database.get_message_history(video.message_data)
    if len(message_history) < 2:
        return False
    latest_command = message_history[1].text
    if latest_command is not None and latest_command.strip().lower() == "gif":
        return True
    return False
