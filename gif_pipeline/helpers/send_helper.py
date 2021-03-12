from __future__ import annotations
import asyncio
import shutil
from typing import Optional, List, Union, TYPE_CHECKING

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.helpers import Helper, find_video_for_message
from gif_pipeline.message import Message
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient, message_data_from_telegram
from gif_pipeline.video_tags import VideoTags

if TYPE_CHECKING:
    from gif_pipeline.helpers.menu_helper import MenuHelper


class GifSendHelper(Helper):

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            channels: List[Channel],
            menu_helper: MenuHelper
    ):
        super().__init__(database, client, worker)
        self.channels = channels
        self.menu_helper = menu_helper

    @property
    def writable_channels(self) -> List[Channel]:
        return [channel for channel in self.channels if not channel.config.read_only]

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
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
            return await self.menu_helper.send_not_gif_warning_menu(chat, message, video, self, dest_str)
        return await self.handle_dest_str(chat, message, video, dest_str, message.message_data.sender_id)

    async def handle_dest_str(
            self,
            chat: Chat,
            cmd: Message,
            video: Message,
            dest_str: str,
            sender_id: int
    ) -> List[Message]:
        if dest_str == "":
            channels = await self.available_channels_for_user(sender_id)
            if not channels:
                return [
                    await self.send_text_reply(
                        chat,
                        cmd,
                        "You do not have permission to send to any available channels."
                    )
                ]
            return await self.menu_helper.destination_menu(chat, cmd, video, self, channels)
        if "<->" in dest_str:
            destinations = dest_str.split("<->", 1)
            return await self.send_two_way_forward(chat, cmd, video, destinations[0], destinations[1], sender_id)
        if "->" in dest_str:
            destinations = dest_str.split("->", 1)
            return await self.send_forward(chat, cmd, video, destinations[0], destinations[1], sender_id)
        if "<-" in dest_str:
            destinations = dest_str.split("<-", 1)
            return await self.send_forward(chat, cmd, video, destinations[1], destinations[0], sender_id)
        destination = self.get_destination_from_name(dest_str)
        if destination is None:
            await self.menu_helper.delete_menu_for_video(video)
            return [await self.send_text_reply(chat, cmd, f"Unrecognised destination: {dest_str}")]
        return await self.send_video(chat, video, cmd, destination, sender_id)

    async def available_channels_for_user(self, user_id: int) -> List[Channel]:
        all_channels = self.writable_channels
        user_is_admin = await asyncio.gather(
            *(self.user_admin_in_channel(user_id, channel) for channel in all_channels)
        )
        return [
            channel for channel, is_admin in zip(all_channels, user_is_admin) if is_admin
        ]

    async def user_admin_in_channel(self, user_id: int, channel: Channel) -> bool:
        admin_ids = await self.client.list_authorized_channel_posters(channel.chat_data)
        return user_id in admin_ids

    async def send_two_way_forward(
            self,
            chat: Chat,
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
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            destination_from: str,
            destination_to: str,
            sender_id: int
    ) -> List[Message]:
        chat_from = self.get_destination_from_name(destination_from)
        if chat_from is None:
            await self.menu_helper.delete_menu_for_video(video)
            return [await self.send_text_reply(chat, cmd_msg, f"Unrecognised destination from: {destination_from}")]
        chat_to = self.get_destination_from_name(destination_to)
        if chat_to is None:
            await self.menu_helper.delete_menu_for_video(video)
            return [await self.send_text_reply(chat, cmd_msg, f"Unrecognised destination to: {destination_to}")]
        # Check permissions in both groups
        from_admin_ids = await self.client.list_authorized_channel_posters(chat_from.chat_data)
        to_admin_ids = await self.client.list_authorized_channel_posters(chat_to.chat_data)
        if sender_id not in from_admin_ids or sender_id not in to_admin_ids:
            await self.menu_helper.delete_menu_for_video(video)
            error_text = "You need to be an admin of both channels to send a forwarded video."
            return [await self.send_text_reply(chat, cmd_msg, error_text)]
        # Send initial message
        tags = video.tags(self.database)
        initial_message = await self.send_message(chat_from, video_path=video.message_data.file_path, tags=tags)
        # Forward message
        new_message = await self.forward_message(chat_to, initial_message, tags)
        # Delete initial message
        await self.client.delete_message(initial_message.message_data)
        initial_message.delete(self.database)
        confirm_text = f"This gif has been sent to {chat_to.chat_data.title} via {chat_from.chat_data.title}"
        confirm_message = await self.menu_helper.after_send_delete_menu(chat, cmd_msg, video, confirm_text)
        messages = [new_message]
        if confirm_message:
            messages.append(confirm_message)
        return messages

    async def send_video(
            self,
            chat: Chat,
            video: Message,
            cmd: Message,
            destination: Chat,
            sender_id: int
    ) -> List[Message]:
        dest_admin_ids = await self.client.list_authorized_channel_posters(destination.chat_data)
        if sender_id not in dest_admin_ids:
            await self.menu_helper.delete_menu_for_video(video)
            return [await self.send_text_reply(chat, cmd, "You do not have permission to post in that channel.")]
        tags = video.tags(self.database)
        new_message = await self.send_message(destination, video_path=video.message_data.file_path, tags=tags)
        confirm_text = f"This gif has been sent to {destination.chat_data.title}."
        confirm_message = await self.menu_helper.after_send_delete_menu(chat, cmd, video, confirm_text)
        messages = [new_message]
        if confirm_message:
            messages.append(confirm_message)
        return messages

    def get_destination_from_name(self, destination_id: Union[str, int]) -> Optional[Chat]:
        destination = None
        for channel in self.writable_channels:
            if channel.chat_data.username == destination_id:
                destination = channel
                break
            if str(channel.chat_data.chat_id) == str(destination_id):
                destination = channel
                break
        return destination

    async def forward_message(self, destination: Chat, message: Message, tags: VideoTags) -> Message:
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
        self.database.save_tags(new_message.message_data, tags)
        destination.add_message(new_message)
        return new_message


def was_giffed(database: Database, video: Message) -> bool:
    message_history = database.get_message_history(video.message_data)
    if len(message_history) < 2:
        return False
    latest_command = message_history[1].text
    if latest_command is not None and latest_command.strip().lower() == "gif":
        return True
    return False
