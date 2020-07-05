from typing import Optional, List

from telethon import Button

from database import Database
from group import Group, Channel
from helpers.helpers import Helper, find_video_for_message
from message import Message
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient


class GifSendHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker, channels: List[Channel]):
        super().__init__(database, client, worker)
        self.channels = channels

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        # If a message says to send to a channel, and replies to a gif, then forward to that channel
        # `send deergifs`, `send cowgifs->deergifs`
        # Needs to handle queueing too?
        text_clean = message.text.lower().strip()
        if not text_clean.startswith("send"):
            return
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(chat, message, "I'm not sure which video you want to video.")]
        if text_clean == "send":
            return await self.destination_menu(chat, video)
        destination = text_clean[4:].strip()
        if "<->" in destination:
            destinations = destination.split("<->", 1)
            return await self.send_two_way_forward(video, destinations[0], destinations[1])
        if "->" in destination:
            destinations = destination.split("->", 1)
            return await self.send_forward(video, destinations[0], destinations[1])
        if "<-" in destination:
            destinations = destination.split("<-", 1)
            return await self.send_forward(video, destinations[1], destinations[0])
        return await self.send_video(video, destination)

    async def destination_menu(self, chat: Group, video: Message) -> List[Message]:
        menu = []
        for channel in self.channels:
            menu.append([Button.inline(channel.chat_data.title, channel.chat_data.chat_id)])
        return [await self.send_text_reply(chat, video, "Which channel should this video be sent to?", buttons=menu)]

    async def send_two_way_forward(self, video: Message, destination1: str, destination2: str) -> List[Message]:
        raise NotImplementedError()

    async def send_forward(self, video: Message, destination_from: str, destination_to: str) -> List[Message]:
        raise NotImplementedError()

    async def send_video(self, video: Message, destination: str):
        raise NotImplementedError()

    def get_destination_from_name(self, destination_name: str) -> Optional[Group]:
        raise NotImplementedError()

    def check_giffed(self, video: Message) -> bool:
        message_history = self.database.get_message_history(video.message_data)
        latest_command = message_history[1].text
        if latest_command is not None and latest_command.strip().lower() == "gif":
            return True
        return False
