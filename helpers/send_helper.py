import shutil
from typing import Optional, List, Union

from telethon import Button

from database import Database
from group import Group, Channel
from helpers.helpers import Helper, find_video_for_message
from message import Message
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient, message_data_from_telegram


class GifSendHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker, channels: List[Channel]):
        super().__init__(database, client, worker)
        self.channels = channels
        self.send_menu = None

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
        dest_str = text_clean[4:].strip()
        if not self.was_giffed(video):
            return await self.send_gif_warning_menu(chat, message, video, dest_str)
        return await self.handle_dest_str(chat, message, video, dest_str)

    async def on_callback_query(self, chat: Group, callback_query: bytes) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == "clear_menu":
            await self.clear_menu()
            return
        if split_data[0] != "send":
            return
        chat_id = split_data[2]
        message = chat.message_by_id(int(split_data[1]))
        if chat_id == "s":
            return await self.handle_dest_str(chat, message, message, split_data[3])
        return await self.send_video(chat, message, chat_id)

    async def handle_dest_str(self, chat: Group, cmd: Message, video: Message, dest_str: str) -> List[Message]:
        if dest_str == "":
            return await self.destination_menu(chat, video)
        if "<->" in dest_str:
            destinations = dest_str.split("<->", 1)
            return await self.send_two_way_forward(chat, cmd, video, destinations[0], destinations[1])
        if "->" in dest_str:
            destinations = dest_str.split("->", 1)
            return await self.send_forward(chat, cmd, video, destinations[0], destinations[1])
        if "<-" in dest_str:
            destinations = dest_str.split("<-", 1)
            return await self.send_forward(chat, cmd, video, destinations[1], destinations[0])
        return await self.send_video(chat, video, dest_str)

    async def send_gif_warning_menu(self, chat: Group, cmd: Message, video: Message, dest_str: str) -> List[Message]:
        await self.clear_menu()
        button_data = f"send:{video.message_data.message_id}:s:{dest_str}"
        menu = [
            [Button.inline("Yes, I am sure", button_data)],
            [Button.inline("No thanks!", "clear_menu")]
        ]
        menu_text = "It looks like this video has not been giffed. Are you sure you want to send it?"
        menu_msg = await self.send_text_reply(chat, cmd, menu_text, buttons=menu)
        self.send_menu = menu_msg
        return [menu_msg]

    async def destination_menu(self, chat: Group, video: Message) -> List[Message]:
        await self.clear_menu()
        menu = []
        for channel in self.channels:
            button_data = f"send:{video.message_data.message_id}:{channel.chat_data.chat_id}"
            menu.append([Button.inline(channel.chat_data.title, button_data)])
        menu_msg = await self.send_text_reply(chat, video, "Which channel should this video be sent to?", buttons=menu)
        self.send_menu = menu_msg
        return [menu_msg]

    async def send_two_way_forward(
            self,
            chat: Group,
            cmd_message: Message,
            video: Message,
            destination1: str,
            destination2: str
    ) -> List[Message]:
        messages = []
        messages += await self.send_forward(chat, cmd_message, video, destination1, destination2),
        messages += await self.send_forward(chat, cmd_message, video, destination2, destination1)
        return messages

    async def send_forward(
            self,
            chat: Group,
            cmd_message: Message,
            video: Message,
            destination_from: str,
            destination_to: str
    ) -> List[Message]:
        chat_from = self.get_destination_from_name(destination_from)
        if chat_from is None:
            return [await self.send_text_reply(chat, cmd_message, f"Unrecognised destination from: {destination_from}")]
        chat_to = self.get_destination_from_name(destination_to)
        if chat_to is None:
            return [await self.send_text_reply(chat, cmd_message, f"Unrecognised destination to: {destination_to}")]
        initial_message = await self.send_message(chat_from, video_path=video.message_data.file_path)
        # Forward message
        new_message = await self.forward_message(chat_to, initial_message)
        # Delete initial message
        await self.client.delete_message(initial_message.message_data)
        # Remove menu
        await self.clear_menu()
        return [new_message]

    async def send_video(self, chat: Group, video: Message, destination_id: Union[str, int]) -> List[Message]:
        destination = self.get_destination_from_name(destination_id)
        if destination is None:
            return [await self.send_text_reply(chat, video, f"Unrecognised destination: {destination_id}")]
        new_message = await self.send_message(destination, video_path=video.message_data.file_path)
        # Remove menu
        await self.clear_menu()
        return [new_message]

    async def clear_menu(self) -> None:
        if self.send_menu is not None:
            await self.client.delete_message(self.send_menu.message_data)
            self.send_menu = None

    def get_destination_from_name(self, destination_id: Union[str, int]) -> Optional[Group]:
        destination = None
        for channel in self.channels:
            if channel.chat_data.username == destination_id:
                destination = channel
                break
            if str(channel.chat_data.chat_id) == str(destination_id):
                destination = channel
                break
        return destination

    def was_giffed(self, video: Message) -> bool:
        message_history = self.database.get_message_history(video.message_data)
        latest_command = message_history[1].text
        if latest_command is not None and latest_command.strip().lower() == "gif":
            return True
        return False

    async def forward_message(self, destination: Group, message: Message) -> Message:
        msg = self.client.forward_message(destination.chat_data, message.message_data)
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
