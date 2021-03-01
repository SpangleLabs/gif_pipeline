import re

import youtube_dl

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, random_sandbox_video_path
from gif_pipeline.message import Message
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.tasks.youtube_dl_task import YoutubeDLTask
from gif_pipeline.telegram_client import TelegramClient


class DownloadHelper(Helper):
    # Scheme (HTTP, HTTPS, FTP and SFTP):
    LINK_REGEX = r'(?:(https?|s?ftp):\/\/)?'
    # www:
    LINK_REGEX += r'(?:www\.)?'
    # Capture domain name or IP. [Group 1...]
    LINK_REGEX += r'('
    # Domain and subdomains (Each up to 64 chars, hypens not allowed on either end)
    LINK_REGEX += r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+)'
    # TLD: [Group 2]
    LINK_REGEX += r'([A-Z]{2,63})'
    # IP Address:
    LINK_REGEX += r'|(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    # End domain name [...Group 1]
    LINK_REGEX += r')'
    # Port: [Group 3]
    LINK_REGEX += r'(?::(\d{1,5}))?'
    # Query path:
    LINK_REGEX += r'(?:[^()\s[\]]*)'

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Chat, message: Message):
        if not message.text:
            return
        # Ignore messages the bot has sent.
        if message.message_data.sender_id == self.client.pipeline_bot_id:
            return
        matches = re.finditer(DownloadHelper.LINK_REGEX, message.text, re.IGNORECASE)
        # Remove gif links, TelegramGifHelper handles those
        links = [match.group(0) for match in matches if self.link_is_monitored(match.group(0))]
        if not links:
            return
        async with self.progress_message(chat, message, "Downloading linked videos"):
            replies = []
            for link in links:
                replies.append(await self.handle_link(chat, message, link))
            return replies

    @staticmethod
    def link_is_monitored(link: str) -> bool:
        exclude_list = [
            "e621.net",  # Handled by MSGHelper
            "imgur.com/a/", "imgur.com/gallery/",  # Handled by ImgurGalleryHelper
            "://t.me/c/",  # Ignored, try to stop telegram loops
            "furaffinity.net/view/",  # Handled FAHelper
            "reddit.com/user/", "reddit.com/u/",  # Ignored, tends to just download 12 second clips
        ]
        return not link.endswith(".gif") and all(exclude not in link for exclude in exclude_list)

    async def handle_link(self, chat: Chat, message: Message, link: str) -> Message:
        try:
            download_filename = await self.download_link(link)
            return await self.send_video_reply(chat, message, download_filename)
        except (youtube_dl.utils.DownloadError, IndexError):
            return await self.send_text_reply(chat, message, f"Could not download video from link: {link}")

    async def download_link(self, link: str) -> str:
        output_path = random_sandbox_video_path("")
        task = YoutubeDLTask(link, output_path)
        return await self.worker.await_task(task)
