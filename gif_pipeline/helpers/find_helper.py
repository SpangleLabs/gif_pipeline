import asyncio
import dataclasses
import json
import logging
from enum import Enum
from typing import Optional, List, TYPE_CHECKING

import vidhash

from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path, cleanup_file
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

HASH_OPTIONS = vidhash.HashOptions(fps=5, settings=vidhash.hash_options.DHash(8))

logger = logging.getLogger(__name__)


class MatchStatus(Enum):
    NO_MATCH = 0
    MATCH = 1
    ERROR = 2


@dataclasses.dataclass
class SearchStatus:
    match: MatchStatus
    messages: List["Message"] = dataclasses.field(default_factory=lambda: [])


@dataclasses.dataclass
class FindStatus:
    video_url: str
    match: MatchStatus
    video_path: str = None
    error: Exception = None
    messages: List["Message"] = dataclasses.field(default_factory=lambda: [])


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
        chunk_length = 3
        # Get source hashes
        source_hashes = await self.duplicate_helper.get_or_create_message_hashes(video.message_data)
        source_vid_hash = await vidhash.hash_video(video.message_data.file_path, HASH_OPTIONS)
        still_searching = True
        playlist_start = 1
        search_status = SearchStatus(MatchStatus.NO_MATCH, messages=[])
        while still_searching:
            playlist_end = playlist_start + chunk_length - 1
            async with self.progress_message(
                    chat,
                    message,
                    f"Checking items {playlist_start}-{playlist_end} of playlist"
            ):
                await self.check_playlist_block(
                    chat,
                    message,
                    source_vid_hash,
                    search_status,
                    link,
                    playlist_start,
                    playlist_end
                )
            if search_status.match == MatchStatus.MATCH:
                return search_status.messages
            playlist_start = playlist_end + 1

    async def check_playlist_block(
            self,
            chat: "Chat",
            message: "Message",
            source_vid_hash: vidhash.VideoHash,
            search_status: SearchStatus,
            playlist_link: str,
            start: int,
            end: int
    ) -> None:
        logger.debug("Checking playlist chunk (%s) from %s to %s", playlist_link, start, end)
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
        video_match_results = await asyncio.gather(
            *[self.send_matching_video(chat, message, url, source_vid_hash) for url in video_urls]
        )
        for match_result in video_match_results:
            search_status.messages.extend(match_result.messages)
            if match_result.match == MatchStatus.MATCH:
                search_status.match = MatchStatus.MATCH

    async def send_matching_video(
            self,
            chat: "Chat",
            message: "Message",
            video_url: str,
            source_vid_hash: vidhash.VideoHash
    ) -> FindStatus:
        video_path = None
        try:
            # Download the video
            logger.debug("Downloading video to check %s", video_url)
            video_path = await self.download_helper.download_link(video_url)
            # Hash video
            logger.debug("Hashing video from feed")
            vid_hash = await vidhash.hash_video(video_path, HASH_OPTIONS)
            # If it matches, then send it
            match_options = vidhash.match_options.PercentageMatch(hamming_dist=5, percentage_overlap=30)
            if not match_options.check_match(source_vid_hash, vid_hash):
                return FindStatus(
                    video_url,
                    MatchStatus.NO_MATCH
                )
            # Convert the video
            logger.debug("Video (%s) matches source video!", video_url)
            output_path = random_sandbox_video_path()
            tasks = video_to_video(video_path, output_path)
            for task in tasks:
                await self.worker.await_task(task)
            # Set source tag
            tags = VideoTags()
            tags.add_tag_value(VideoTags.source, video_url)
            # Send video
            result_msg = await self.send_video_reply(
                chat, message, output_path, tags, f"Found video in feed: {video_url}"
            )
            return FindStatus(
                video_url,
                MatchStatus.MATCH,
                video_path=output_path,
                messages=[result_msg]
            )
        except Exception as e:
            err_msg = self.send_text_reply(
                chat, message, f"Could not check video from feed: {video_url}"
            )
            return FindStatus(
                video_url,
                MatchStatus.ERROR,
                error=e,
                messages=[err_msg]
            )
        finally:
            cleanup_file(video_path)
