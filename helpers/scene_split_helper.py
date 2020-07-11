import asyncio
from typing import Optional, List, Tuple

from scenedetect import StatsManager, SceneManager, VideoManager, ContentDetector, FrameTimecode
from telethon import Button

from database import Database
from group import Group
from helpers.helpers import find_video_for_message
from helpers.video_cut_helper import VideoCutHelper
from message import Message
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient


class SceneSplitHelper(VideoCutHelper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)
        self.confirmation_menu_msg = None
        self.confirmation_menu_scene_list = None

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        text_clean = message.text.strip().lower()
        key_words = ["split scenes", "scenesplit", "scene split"]
        args = None
        for key_word in key_words:
            if text_clean.startswith(key_word):
                args = text_clean[len(key_word):].strip()
        if args is None:
            return None
        if len(args) == 0:
            threshold = 30
        else:
            try:
                threshold = int(args)
            except ValueError:
                return [await self.send_text_reply(
                    chat,
                    message,
                    "I don't understand that threshold setting. Please specify an integer. e.g. 'split scenes 20'"
                )]
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(
                chat,
                message,
                "I am not sure which video you would like to split. Please reply to the video with your split command."
            )]
        async with self.progress_message(chat, message, "Calculating scene list"):
            loop = asyncio.get_event_loop()
            scene_list = await loop.run_in_executor(None, self.calculate_scene_list, video, threshold)
        if len(scene_list) == 1:
            return [await self.send_text_reply(chat, message, "This video contains only 1 scene.")]
        return [await self.confirmation_menu(chat, message, video, threshold, scene_list)]

    async def on_callback_query(self, chat: Group, callback_query: bytes, sender_id: int) -> Optional[List[Message]]:
        query_split = callback_query.decode().split(":")
        if query_split[0] == "split_clear_menu":
            await self.clear_confirmation_menu()
            return []
        if query_split[0] != "split":
            return None
        if self.confirmation_menu_msg is None:
            return None
        message = chat.message_by_id(self.confirmation_menu_msg.message_data.reply_to)
        video_id = int(query_split[1])
        video = chat.message_by_id(video_id)
        scene_list = self.confirmation_menu_scene_list
        progress_text = f"Splitting video into {len(scene_list)} scenes"
        await self.clear_confirmation_menu()
        async with self.progress_message(chat, message, progress_text):
            return await self.split_scenes(chat, message, video, scene_list)

    @staticmethod
    def calculate_scene_list(video: Message, threshold: int = 30) -> List[Tuple[FrameTimecode, FrameTimecode]]:
        video_manager = VideoManager([video.message_data.file_path])
        stats_manager = StatsManager()
        scene_manager = SceneManager(stats_manager)
        scene_manager.add_detector(ContentDetector(threshold=threshold))
        try:
            video_manager.start()
            base_timecode = video_manager.get_base_timecode()
            scene_manager.detect_scenes(frame_source=video_manager)
            scene_list = scene_manager.get_scene_list(base_timecode)
            return scene_list
        finally:
            video_manager.release()

    async def confirmation_menu(
            self,
            chat: Group,
            message: Message,
            video: Message,
            threshold: int,
            scene_list: List[Tuple[FrameTimecode, FrameTimecode]]
    ) -> Message:
        await self.clear_confirmation_menu()
        menu = [
            [Button.inline("Yes please", f"split:{video.message_data.message_id}")],
            [Button.inline("No thank you", "split_clear_menu")]
        ]
        menu_text = \
            f"Using a threshold of {threshold}, this video would be split into {len(scene_list)} scenes. " \
            f"Would you like to proceed with cutting?"
        menu_msg = await self.send_text_reply(chat, message, menu_text, buttons=menu)
        self.confirmation_menu_msg = menu_msg
        self.confirmation_menu_scene_list = scene_list
        return menu_msg

    async def split_scenes(
            self,
            chat: Group,
            message: Message,
            video: Message,
            scene_list: List[Tuple[FrameTimecode, FrameTimecode]]
    ) -> Optional[List[Message]]:
        cut_videos = await asyncio.gather(*[
            self.cut_video(
                video,
                start_time.get_timecode(),
                end_time.previous_frame().get_timecode()
            ) for (start_time, end_time) in scene_list
        ])
        video_replies = []
        for new_path in cut_videos:
            video_replies.append(await self.send_video_reply(chat, message, new_path))
        return video_replies

    async def clear_confirmation_menu(self) -> None:
        if self.confirmation_menu_msg is not None:
            await self.client.delete_message(self.confirmation_menu_msg.message_data)
            self.confirmation_menu_msg.delete(self.database)
            self.confirmation_menu_msg = None
            self.confirmation_menu_scene_list = None
