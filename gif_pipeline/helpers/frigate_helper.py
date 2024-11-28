import asyncio
import datetime
import logging
import uuid
from typing import Optional, List

import aiohttp
import dateutil.parser

from gif_pipeline.chat import Chat
from gif_pipeline.database import Database
from gif_pipeline.helpers.download_helper import DownloadHelper
from gif_pipeline.helpers.helpers import Helper, random_video_path_with_cleanup
from gif_pipeline.message import Message
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient
from gif_pipeline.video_tags import VideoTags

logger = logging.getLogger(__name__)

class FrigateHelper(Helper):
    MAX_EXPORT_PROCESSING_WAIT_SECS = 300
    SLEEP_BETWEEN_CHECKS_SECS = 5

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            dl_helper: DownloadHelper,
            frigate_url: str,
    ) -> None:
        super().__init__(database, client, worker)
        self.dl_helper = dl_helper
        self.frigate_url = frigate_url

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        clean_args = message.text.lower().strip().split()
        if len(clean_args) == 0 or clean_args[0] != "frigate":
            return None
        if len(clean_args) != 4:
            error_msg = (
                "I'm not sure what you want from Frigate, please specify your command in the format "
                "`frigate <camera_name> <start_time> <end_time>`"
            )
            return [await self.send_message(chat, reply_to_msg=message, text=error_msg)]
        camera_name = clean_args[1]
        start_time_str = clean_args[2]
        try:
            start_time = self.parse_time(start_time_str)
        except ValueError:
            return [await self.send_message(chat, reply_to_msg=message, text="Invalid start time")]
        end_time_str = clean_args[3]
        try:
            end_time = self.parse_time(end_time_str)
        except ValueError:
            return [await self.send_message(chat, reply_to_msg=message, text="Invalid end time")]
        # Get the export
        return await self.create_export(chat, message, camera_name, start_time, end_time)

    def parse_time(self, time_str: str) -> datetime.datetime:
        time_obj = dateutil.parser.parse(time_str)
        # TODO: If time only, use today's date, provided that's in the past
        return time_obj

    async def create_export(
            self,
            chat: Chat,
            message: Message,
            camera: str,
            start: datetime.datetime,
            end: datetime.datetime,
    ) -> Optional[List[Message]]:
        post_url = f"{self.frigate_url}/api/export/{camera}/start/{start.timestamp()}/end/{end.timestamp()}"
        today = datetime.date.today()
        rand_uuid = uuid.uuid4()
        export_name = f"gif_pipeline_{today.isoformat()}_{rand_uuid}"
        post_body = {
            "name": export_name,
        }
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(post_url, json=post_body) as resp:
                    resp_data = await resp.json()
            except Exception as err:
                logger.warning("Failed to create Frigate export", exc_info=err)
                return [await self.send_message(chat, reply_to_msg=message, text="Failed to create export.")]
            # Check the export creation response
            if not resp_data["success"]:
                failure_message = resp_data["message"]
                return [await self.send_message(chat, reply_to_msg=message, text=f"Frigate rejected export request: {failure_message}")]
            # Wait for export to complete
            try:
                async with self.progress_message(chat, message, "Waiting for Frigate export to complete"):
                    media_path = await self.wait_until_export_complete(session, export_name)
            except Exception as err:
                logger.warning("Frigate export failed to complete", exc_info=err)
                return [await self.send_message(chat, reply_to_msg=message, text="Failed to complete export.")]
            # Download the video
            async with self.progress_message(chat, message, "Downloading video from Frigate"):
                dl_url = f"{self.frigate_url}" + media_path.removeprefix("/media/frigate")
                with random_video_path_with_cleanup() as dl_path:
                    async with session.get(dl_url) as resp:
                        resp.raise_for_status()
                        with open(dl_path, "wb") as f:
                            async for chunk in resp.content.iter_chunked(8192):
                                f.write(chunk)
                    # Create tags object
                    tags = VideoTags({VideoTags.source: {dl_url}})
                    # Upload the video
                    return [await self.send_video_reply(chat, message, dl_path, tags)]

    async def wait_until_export_complete(self, session: aiohttp.ClientSession, export_name: str) -> str:
        start_time = datetime.datetime.now(datetime.timezone.utc)
        end_time = start_time + datetime.timedelta(seconds=self.MAX_EXPORT_PROCESSING_WAIT_SECS)
        exports_list_url = f"{self.frigate_url}/api/exports"
        resp_data = None
        while datetime.datetime.now(datetime.timezone.utc) < end_time:
            async with session.get(exports_list_url) as resp:
                resp_data = await resp.json()
            found = False
            for export_data in resp_data:
                if export_data["name"] == export_name:
                    found = True
                    if export_data["in_progress"]:
                        logger.info("Waiting for Frigate export \"%s\" to complete", export_name)
                        await asyncio.sleep(self.SLEEP_BETWEEN_CHECKS_SECS)
                    else:
                        logger.info("Frigate export \"%s\" is complete", export_name)
                        return export_data["video_path"]
            if not found:
                logger.info("Could not find Frigate export \"%s\"", export_name)
                await asyncio.sleep(self.SLEEP_BETWEEN_CHECKS_SECS)
        if resp_data is None:
            raise ValueError("Did not fetch exports data from Frigate API")



