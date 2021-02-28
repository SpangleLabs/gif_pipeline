from typing import Optional

from gif_pipeline.database import Database
from gif_pipeline.group import Group
from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class VideoRotateHelper(Helper):
    ROTATE_CLOCK = ["right", "90", "clock", "clockwise", "90clock", "90clockwise"]
    ROTATE_ANTICLOCK = [
        "left", "270", "anticlock", "anticlockwise", "90anticlock", "90anticlockwise", "cclock", "counterclock",
        "counterclockwise", "90cclock", "90counterclock", "90counterclockwise"
    ]
    ROTATE_180 = [
        "180", "180clockwise", "180anticlockwise", "180clock", "180anticlock", "180cclock", "180counterclock",
        "180counterclockwise"
    ]
    FLIP_HORIZONTAL = ["horizontal", "leftright"]
    FLIP_VERTICAL = ["vertical", "topbottom"]

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Group, message: Message):
        # If a message has text saying to rotate, and is a reply to a video, then cut it
        # `rotate left`, `rotate right`, `flip horizontal`?, `rotate 90`, `rotate 180`
        text_clean = message.text.strip().lower().replace("-", "")
        if text_clean.startswith("rotate"):
            transpose = self.get_rotate_direction(text_clean[len("rotate"):].strip())
        elif text_clean.startswith("flip"):
            transpose = self.get_flip_direction(text_clean[len("flip"):].strip())
        else:
            return
        video = find_video_for_message(chat, message)
        if video is None:
            await self.send_text_reply(chat, message, "Cannot work out which video you want to rotate/flip.")
        if transpose is None:
            return [await self.send_text_reply(chat, message, "I do not understand this rotate/flip command.")]
        async with self.progress_message(chat, message, "Rotating or flipping video.."):
            output_path = random_sandbox_video_path()
            task = FfmpegTask(
                inputs={video.message_data.file_path: None},
                outputs={output_path: f"-vf \"{transpose}\""}
            )
            await self.worker.await_task(task)
            return [await self.send_video_reply(chat, message, output_path)]

    @staticmethod
    def get_rotate_direction(text_clean: str) -> Optional[str]:
        text_clean = text_clean.replace(" ", "")
        if text_clean in VideoRotateHelper.ROTATE_CLOCK:
            return "transpose=clock"
        if text_clean in VideoRotateHelper.ROTATE_ANTICLOCK:
            return "transpose=cclock"
        if text_clean in VideoRotateHelper.ROTATE_180:
            return "transpose=clock,transpose=clock"
        return None

    @staticmethod
    def get_flip_direction(text_clean: str) -> Optional[str]:
        text_clean = text_clean.replace(" ", "")
        if text_clean in VideoRotateHelper.FLIP_HORIZONTAL:
            return "transpose=cclock_flip,transpose=clock"
        if text_clean in VideoRotateHelper.FLIP_VERTICAL:
            return "transpose=clock,transpose=cclock_flip"
        return None
