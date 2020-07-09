import glob
import os
import shutil
from typing import Optional, List, Set

import imagehash
from PIL import Image

from database import Database
from group import Channel, WorkshopGroup, Group
from helpers.helpers import Helper
from message import Message, MessageData
from tasks.ffmpeg_task import FfmpegTask
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient


class DuplicateHelper(Helper):
    blank_frame_hash = "0000000000000000"

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def initialise_hashes(self, workshops: List[WorkshopGroup]):
        # Initialise, get all channels, get all videos, decompose all, add to the master hash
        workshop_ids = {workshop.chat_data.chat_id: workshop for workshop in workshops}
        messages_needing_hashes = self.database.get_messages_needing_hashing()
        for message_data in messages_needing_hashes:
            new_hashes = await self.create_message_hashes(message_data)
            if message_data.chat_id in workshop_ids:
                workshop = workshop_ids[message_data.chat_id]
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
        hashes = set()
        for image_file in glob.glob(f"{message_decompose_path}/*.png"):
            image = Image.open(image_file)
            image_hash = str(imagehash.dhash(image))
            hashes.add(image_hash)
        # Delete the images
        try:
            shutil.rmtree(message_decompose_path)
        except FileNotFoundError:
            pass
        # Save hashes
        self.database.save_hashes(message_data, hashes)
        # Return hashes
        return hashes

    async def check_hash_in_store(self, chat: Group, image_hashes: Set[str], message: Message) -> Optional[Message]:
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
            chat: Group,
            new_message: Message,
            potential_matches: Set[MessageData],
            has_blank_frame: bool
    ):
        warning_messages = []
        if has_blank_frame:
            warning_messages.append("This video contains at least one blank frame.")
        if potential_matches:
            message_links = []
            for message in potential_matches:
                chat_data = self.database.get_chat_by_id(message.chat_id) or chat.chat_data
                message_links.append(chat_data.telegram_link_for_message(message))
            warning_messages.append("This video might be a duplicate of:\n" + "\n".join(message_links))
        await self.send_text_reply(chat, new_message, "\n".join(warning_messages))

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

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        # If message has a video, decompose it if necessary, then check images against master hash
        if isinstance(chat, Channel):
            await self.get_or_create_message_hashes(message.message_data)
            return
        if message.message_data.file_path is None:
            if message.message_data.text.strip().lower() == "check":
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
        progress_text = "Checking whether this video has been seen before"
        async with self.progress_message(chat, message, progress_text):
            hashes = await self.get_or_create_message_hashes(message.message_data)
            warning_msg = await self.check_hash_in_store(chat, hashes, message)
        if warning_msg is not None:
            return [warning_msg]

    async def on_deleted_message(self, chat: Group, message: Message):
        self.database.remove_message_hashes(message.message_data)
