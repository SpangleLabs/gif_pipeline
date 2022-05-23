import asyncio
import json
import logging
from typing import Optional, List, TYPE_CHECKING, Set
import uuid

from gif_pipeline.database import chunks
from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from gif_pipeline.helpers.video_helper import video_to_video
from gif_pipeline.tasks.youtube_dl_task import YoutubeDLDumpJsonTask
from gif_pipeline.video_tags import VideoTags

if TYPE_CHECKING:
    from gif_pipeline.chat import Chat
    from gif_pipeline.database import Database
    from gif_pipeline.helpers.download_helper import DownloadHelper
    from gif_pipeline.helpers.duplicate_helper import DuplicateHelper
    from gif_pipeline.message import Message
    from gif_pipeline.tasks.task_worker import TaskWorker
    from gif_pipeline.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


class FindHelper(Helper):

    def __init__(
            self,
            database: "Database",
            client: "TelegramClient",
            worker: "TaskWorker",
            duplicate_helper: "DuplicateHelper",
            download_helper: "DownloadHelper"
    ):
        super().__init__(database, client, worker)
        self.duplicate_helper = duplicate_helper
        self.download_helper = download_helper

    def is_priority(self, chat: "Chat", message: "Message") -> bool:
        clean_args = message.text.strip().split()
        if not clean_args or clean_args[0].lower() not in ["find"]:
            return False
        return True

    async def on_new_message(self, chat: "Chat", message: "Message") -> Optional[List["Message"]]:
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
        chunk_length = 4
        # Get source hashes
        source_hashes = await self.duplicate_helper.get_or_create_message_hashes(video.message_data)
        still_searching = True
        playlist_start = 1
        while still_searching:
            playlist_end = playlist_start + chunk_length - 1
            async with self.progress_message(
                    chat,
                    message,
                    f"Checking items {playlist_start}-{playlist_end} of playlist"
            ):
                responses = await self.check_playlist_block(
                    chat,
                    message,
                    source_hashes,
                    link,
                    playlist_start,
                    playlist_end
                )
            if responses:
                return responses
            playlist_start = playlist_end + 1

    async def check_playlist_block(
            self,
            chat: "Chat",
            message: "Message",
            source_hashes: Set[str],
            playlist_link: str,
            start: int,
            end: int
    ) -> Optional[List["Message"]]:
        playlist_task = YoutubeDLDumpJsonTask(playlist_link, end, start)
        playlist_resp = await self.worker.await_task(playlist_task)
        try:
            playlist_data = [
                json.loads(line)
                for line in playlist_resp.split("\n")
            ]
        except json.JSONDecodeError as e:
            logger.error("Could not decode json response for playlist: %s", playlist_link, exc_info=e)
            return [await self.send_text_reply(chat, message, "Could not decode playlist response")]
        if not playlist_data:
            return [await self.send_text_reply(chat, message, "Could not find target video in feed")]
        video_urls = [playlist_item["webpage_url"] for playlist_item in playlist_data]
        matching_video_msgs = await asyncio.gather(
            *[self.send_matching_video(chat, message, url, source_hashes) for url in video_urls]
        )
        if any(matching_video_msgs):
            return [
                matching_msg
                for matching_msg in matching_video_msgs
                if matching_msg is not None
            ]

    async def send_matching_video(
            self,
            chat: "Chat",
            message: "Message",
            video_url: str,
            source_hashes: Set[str]
    ) -> Optional["Message"]:
        # Download the video
        video_path = await self.download_helper.download_link(video_url)
        # Convert the video
        output_path = random_sandbox_video_path()
        tasks = video_to_video(video_path, output_path)
        for task in tasks:
            await self.worker.await_task(task)
        # Hash video
        decompose_path = f"sandbox/decompose/search/{uuid.uuid4()}/"
        hash_set = await self.duplicate_helper.create_message_hashes_in_dir(output_path, decompose_path)
        # If it matches, then send it
        hash_set.discard(self.duplicate_helper.blank_frame_hash)
        if len(hash_set.union(source_hashes)) > 3:
            tags = VideoTags()
            tags.add_tag_value(VideoTags.source, video_url)
            return await self.send_video_reply(chat, message, output_path, tags, f"Found video in feed: {video_url}")
