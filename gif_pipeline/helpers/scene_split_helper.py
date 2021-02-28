from __future__ import annotations
import asyncio
from typing import Optional, List, Tuple, TYPE_CHECKING

from scenedetect import StatsManager, SceneManager, VideoManager, ContentDetector, FrameTimecode

from database import Database
from group import Group
from helpers.helpers import find_video_for_message
from helpers.video_cut_helper import VideoCutHelper
from message import Message
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient

if TYPE_CHECKING:
    from helpers.menu_helper import MenuHelper


class SceneSplitHelper(VideoCutHelper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker, menu_helper: MenuHelper):
        super().__init__(database, client, worker)
        self.menu_helper = menu_helper

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
        return [await self.menu_helper.split_scenes_confirmation(chat, message, video, threshold, scene_list, self)]

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
