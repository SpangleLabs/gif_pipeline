import re

import youtube_dl

from database import Database
from group import Group
from helpers.helpers import Helper, random_sandbox_video_path
from message import Message
from tasks.task_worker import TaskWorker
from tasks.youtube_dl_task import YoutubeDLTask
from telegram_client import TelegramClient


class DownloadHelper(Helper):
    LINK_REGEX = r'('
    # Scheme (HTTP, HTTPS, FTP and SFTP):
    LINK_REGEX += r'(?:(https?|s?ftp):\/\/)?'
    # www:
    LINK_REGEX += r'(?:www\.)?'
    LINK_REGEX += r'('
    # Host and domain (including ccSLD):
    LINK_REGEX += r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+)'
    # TLD:
    LINK_REGEX += r'([A-Z]{2,6})'
    # IP Address:
    LINK_REGEX += r'|(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    LINK_REGEX += r')'
    # Port:
    LINK_REGEX += r'(?::(\d{1,5}))?'
    # Query path:
    LINK_REGEX += r'(?:(\/\S+)*)'
    LINK_REGEX += r')'

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        if not message.text:
            return
        # TODO: something not awful
        if "Could not download video from link" in message.text:
            return
        matches = re.findall(DownloadHelper.LINK_REGEX, message.text, re.IGNORECASE)
        # Remove gif links, TelegramGifHelper handles those
        links = [match[0] for match in matches if self.link_is_monitored(match[0])]
        if not links:
            return
        async with self.progress_message(chat, message, "Downloading linked videos"):
            replies = []
            for link in links:
                replies.append(await self.handle_link(chat, message, link))
            return replies

    @staticmethod
    def link_is_monitored(link: str) -> bool:
        exclude_list = ["e621.net", "imgur.com/a/", "imgur.com/gallery/"]
        return not link.endswith(".gif") and all(exclude not in link for exclude in exclude_list)

    async def handle_link(self, chat: Group, message: Message, link: str) -> Message:
        try:
            download_filename = await self.download_link(link)
            return await self.send_video_reply(chat, message, download_filename)
        except (youtube_dl.utils.DownloadError, IndexError):
            return await self.send_text_reply(chat, message, f"Could not download video from link: {link}")

    async def download_link(self, link: str) -> str:
        output_path = random_sandbox_video_path("")
        task = YoutubeDLTask(link, output_path)
        return await self.worker.await_task(task)