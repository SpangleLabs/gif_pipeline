import json
import logging
from typing import Optional, List, TYPE_CHECKING

from gif_pipeline.chat import Chat
from gif_pipeline.database import chunks
from gif_pipeline.helpers.helpers import Helper, find_video_for_message
from gif_pipeline.message import Message
from gif_pipeline.tasks.youtube_dl_task import YoutubeDLDumpJsonTask

if TYPE_CHECKING:
    from gif_pipeline.database import Database
    from gif_pipeline.helpers.duplicate_helper import DuplicateHelper
    from gif_pipeline.tasks.task_worker import TaskWorker
    from gif_pipeline.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


class FindHelper(Helper):

    def __init__(
            self,
            database: "Database",
            client: "TelegramClient",
            worker: TaskWorker,
            duplicate_helper: DuplicateHelper
    ):
        super().__init__(database, client, worker)
        self.duplicate_helper = duplicate_helper

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        video = find_video_for_message(chat, message)
        if not video:
            return None
        msg_args = message.text.split()
        if len(msg_args) == 0 or msg_args[0].lower() != "find":
            return None
        msg_args = msg_args[1:]
        if msg_args[0] == "in":
            msg_args = msg_args[1:]
        if not msg_args:
            return [
                await self.send_text_reply(
                    chat,
                    message,
                    "Please specify a playlist link to search for a match to the given video"
                )
            ]
        link = msg_args[0]
        async with self.progress_message(chat, message, f"Getting playlist data for {link}"):
            # Get source hashes
            source_hashes = self.duplicate_helper.get_or_create_message_hashes(video.message_data)
            # Get the playlist information
            playlist_task = YoutubeDLDumpJsonTask(link)
            playlist_resp = await self.worker.await_task(playlist_task)
            try:
                playlist_data = json.loads(playlist_resp)
            except json.JSONDecodeError as e:
                logger.error("Could not decode json response for playlist: %s", link, exc_info=e)
        # Start going through videos on the playlist
        video_urls = [playlist_item["webpage_url"] for playlist_item in playlist_data]
        video_count = 0
        chunk_length = 4
        for video_url_chunk in chunks(video_urls, chunk_length):
            async with self.progress_message(chat, message, f"Checking {video_count+1}-{video_count+chunk_length+1} of {video_urls} videos"):
                pass  # TODO

