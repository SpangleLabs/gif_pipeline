import glob
import os
import shutil
from multiprocessing.pool import ThreadPool
from typing import Optional, List, Set, Dict

import imagehash
from PIL import Image

from gif_pipeline.database import Database
from gif_pipeline.chat import WorkshopGroup, Chat
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.message import Message, MessageData
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient
from gif_pipeline.utils import tqdm_gather


def hash_image(image_file: str) -> str:
    image = Image.open(image_file)
    image_hash = str(imagehash.dhash(image))
    return image_hash


class DuplicateHelper(Helper):
    blank_frame_hash = "0000000000000000"

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)
        self.hash_pool = ThreadPool(os.cpu_count())

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
        # Create hashes for message
        new_hashes = await self.create_message_hashes(message_data)
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
        # Decompose video into images
        os.makedirs(message_decompose_path, exist_ok=True)
        await self.decompose_video(message_data.file_path, message_decompose_path)
        # Hash the images
        image_files = glob.glob(f"{message_decompose_path}/*.png")
        hash_list = self.hash_pool.map(hash_image, image_files)
        hash_set = set(hash_list)
        # Delete the images
        try:
            shutil.rmtree(message_decompose_path)
        except FileNotFoundError:
            pass
        # Save hashes
        self.database.save_hashes(message_data, hash_set)
        # Return hashes
        return hash_set

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

    async def post_duplicate_warning(
            self,
            chat: Chat,
            new_message: Message,
            potential_matches: Set[MessageData],
            has_blank_frame: bool
    ) -> Message:
        warning_messages = []
        if has_blank_frame:
            warning_messages.append("This video contains at least one blank frame.")
        if potential_matches:
            message_links = []
            for message in potential_matches:
                chat_data = self.database.get_chat_by_id(message.chat_id) or chat.chat_data
                message_links.append(chat_data.telegram_link_for_message(message))
            warning_messages.append("This video might be a duplicate of:\n" + "\n".join(message_links))
        return await self.send_text_reply(chat, new_message, "\n".join(warning_messages))

    @staticmethod
    def get_image_hashes(decompose_directory: str):
        hashes = []
        for image_file in glob.glob(f"{decompose_directory}/*.png"):
            image = Image.open(image_file)
            image_hash = str(imagehash.average_hash(image))
            hashes.append(image_hash)
        return hashes

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
