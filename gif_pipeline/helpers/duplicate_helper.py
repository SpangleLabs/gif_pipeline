import logging
import os
import shutil
from concurrent.futures.process import ProcessPoolExecutor
from multiprocessing.pool import ThreadPool
from typing import Optional, List, Set, Dict

from gif_pipeline.database import Database
from gif_pipeline.chat import WorkshopGroup, Chat
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.message import Message, MessageData
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask
from gif_pipeline.tasks.ffmprobe_task import FFprobeTask
from gif_pipeline.tasks.hash_dir_task import HashDirectoryTask
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient
from gif_pipeline.utils import tqdm_gather


logger = logging.getLogger(__name__)


class DuplicateHelper(Helper):
    blank_frame_hash = "0000000000000000"
    MAX_AUTO_HASH_LENGTH_SECONDS = 60 * 30

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)
        self.hash_pool = ThreadPool(os.cpu_count())
        self.hash_pool_executor = ProcessPoolExecutor(os.cpu_count())

    async def initialise_hashes(self, workshops: List[WorkshopGroup]):
        # Initialise, get all channels, get all videos, decompose all, add to the master hash
        workshop_ids = {workshop.chat_data.chat_id: workshop for workshop in workshops}
        messages_needing_hashes = self.database.get_messages_needing_hashing()
        await tqdm_gather(
            [self.initialise_message(message_data, workshop_ids) for message_data in messages_needing_hashes],
            desc="Hashing messages"
        )

    async def initialise_message(self, message_data: MessageData, workshop_dict: Dict[int, WorkshopGroup]) -> None:
        # Skip any messages in workshops which are disabled
        workshop = workshop_dict.get(message_data.chat_id)
        if workshop is not None and not workshop.config.duplicate_detection:
            return
        # Skip if the video is over the max length
        length_task = FFprobeTask(
            global_options=["-v error"],
            inputs={message_data.file_path: "-show_entries format=duration -of default=noprint_wrappers=1:nokey=1"}
        )
        video_length = float(await self.worker.await_task(length_task))
        if video_length > self.MAX_AUTO_HASH_LENGTH_SECONDS:
            logger.info("Skipping initialising video due to length: %s", message_data)
        # Create hashes for message
        try:
            new_hashes = await self.create_message_hashes(message_data)
        except:
            logger.error(f"Duplicate helper failed to check video during startup: {message_data}")
            if workshop is not None:
                message = workshop.message_by_id(message_data.message_id)
                await self.send_text_reply(
                    workshop,
                    message,
                    "During startup, duplicate helper failed to check this video"
                )
            return
        # Send alerts for workshop messages
        if workshop is not None:
            message = workshop.message_by_id(message_data.message_id)
            await self.check_hash_in_store(workshop, new_hashes, message)

    async def get_or_create_message_hashes(self, message_data: MessageData) -> Set[str]:
        existing_hashes = self.get_message_hashes(message_data)
        if existing_hashes is not None:
            return set(existing_hashes)
        return await self.create_message_hashes(message_data)

    def get_message_hashes(self, message_data: MessageData) -> Optional[List[str]]:
        hashes = self.database.get_hashes_for_message(message_data)
        if hashes:
            return hashes
        return None

    async def create_message_hashes(self, message_data: MessageData) -> Set[str]:
        if not message_data.has_video:
            return set()
        message_decompose_path = f"sandbox/decompose/{message_data.chat_id}-{message_data.message_id}/"
        # Hash video
        hash_set = await self.create_message_hashes_in_dir(message_data.file_path, message_decompose_path)
        # Save hashes
        self.database.save_hashes(message_data, hash_set)
        # Return hashes
        return hash_set

    async def create_message_hashes_in_dir(self, video_path: str, decompose_path: str) -> Set[str]:
        try:
            # Decompose video into images
            os.makedirs(decompose_path, exist_ok=True)
            await self.decompose_video(video_path, decompose_path)
            # Hash the images
            hash_task = HashDirectoryTask(decompose_path, self.hash_pool_executor)
            hash_set = await self.worker.await_task(hash_task)
            return hash_set
        finally:
            # Delete the images
            try:
                shutil.rmtree(decompose_path)
            except FileNotFoundError:
                pass

    async def check_hash_in_store(
            self,
            chat: WorkshopGroup,
            image_hashes: Set[str],
            message: Message
    ) -> Optional[Message]:
        if not image_hashes:
            return None
        has_blank_frame = self.blank_frame_hash in image_hashes
        if has_blank_frame:
            image_hashes.remove(self.blank_frame_hash)
        matching_messages = set(self.database.get_messages_for_hashes(image_hashes))
        # Get root parent
        msg_history = self.database.get_message_history(message.message_data)
        msg_family = set(self.database.get_message_family(msg_history[-1]))
        # warning messages
        warning_messages = matching_messages - msg_family
        warning_msg = None
        if len(warning_messages) > 0 or has_blank_frame:
            warning_msg = await self.post_duplicate_warning(chat, message, warning_messages, has_blank_frame)
        return warning_msg

    def get_duplicate_warnings(
            self,
            potential_matches: Set[MessageData],
            has_blank_frame: bool
    ) -> List[str]:
        warning_messages = []
        if has_blank_frame:
            warning_messages.append("This video contains at least one blank frame.")
        if potential_matches:
            message_links = []
            for message in potential_matches:
                chat_data = self.database.get_chat_by_id(message.chat_id)
                message_links.append(chat_data.telegram_link_for_message(message))
            warning_messages.append("This video might be a duplicate of:\n" + "\n".join(message_links))
        return warning_messages

    async def post_duplicate_warning(
            self,
            chat: Chat,
            new_message: Message,
            potential_matches: Set[MessageData],
            has_blank_frame: bool
    ) -> Message:
        warning_messages = self.get_duplicate_warnings(potential_matches, has_blank_frame)
        return await self.send_text_reply(chat, new_message, "\n".join(warning_messages))

    async def decompose_video(self, video_path: str, decompose_dir_path: str):
        task = FfmpegTask(
            inputs={video_path: None},
            outputs={f"{decompose_dir_path}/out%d.png": "-vf fps=5 -vsync 0"},
            global_options="-y"
        )
        await self.worker.await_task(task)

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        # For channels, just hash it, don't post warnings
        if not isinstance(chat, WorkshopGroup):
            await self.get_or_create_message_hashes(message.message_data)
            return
        # Ignore messages in workshops with duplicate detection off
        if not chat.config.duplicate_detection:
            return
        # If no file, check if someone has requested manual check
        if message.message_data.file_path is None:
            if message.message_data.text.strip().lower() == "check":
                self.usage_counter.inc()
                reply_to = chat.message_by_id(message.message_data.reply_to)
                if reply_to is None:
                    return [await self.send_text_reply(chat, message, "I can't check a message without a video")]
                async with self.progress_message(chat, message, "Checking whether that video has been seen before"):
                    hashes = await self.get_or_create_message_hashes(reply_to.message_data)
                    warning_msg = await self.check_hash_in_store(chat, hashes, reply_to)
                    if warning_msg is None:
                        return [
                            await self.send_text_reply(chat, message, "That video does not match any other videos.")
                        ]
                    return [warning_msg]
            return
        # If message has a video, decompose it if necessary, then check images against master hash
        progress_text = "Checking whether this video has been seen before"
        async with self.progress_message(chat, message, progress_text):
            # If hashes already exist, don't check it again (it has been sent from a workshop)
            existing_hashes = self.get_message_hashes(message.message_data)
            if existing_hashes:
                return
            hashes = await self.get_or_create_message_hashes(message.message_data)
            warning_msg = await self.check_hash_in_store(chat, hashes, message)
        if warning_msg is not None:
            return [warning_msg]

    async def on_deleted_message(self, chat: Chat, message: Message):
        self.database.remove_message_hashes(message.message_data)

    def can_handle(self, chat: Chat, message: Message) -> bool:
        return True
