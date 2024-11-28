from gif_pipeline.database import Database
from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, find_video_for_message, random_sandbox_video_path
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class VideoSpeedHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Chat, message: Message):
        text_clean = message.text.lower().strip()
        if not text_clean.startswith("speed"):
            return None
        self.usage_counter.inc()
        text_args = text_clean.split()
        if len(text_args) != 2:
            return [await self.send_text_reply(
                chat,
                message,
                "Please specify how much to speed up the video, in the format `speed 2x`",
            )]
        speed_arg = text_args[1]
        if speed_arg.endswith("x"):
            speed_arg = speed_arg[:-1]
        speed = self.parse_speed(speed_arg)
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(
                chat,
                message,
                "I am not sure which video you would like to speed up. Please reply to the video with your speed command."
            )]
        async with self.progress_message(chat, message, "Altering video speed"):
            output_path = await self.speed_up_video(video, speed)
            tags = video.tags(self.database)
            return [await self.send_video_reply(chat, message, output_path, tags)]

    # noinspection PyMethodMayBeStatic
    def parse_speed(self, speed_arg: str) -> float:
        if "/" in speed_arg:
            numerator, denominator = speed_arg.split("/")
            return float(numerator) / float(denominator)
        return float(speed_arg)

    async def speed_up_video(self, video: Message, speed: float) -> str:
        new_path = random_sandbox_video_path()
        task = FfmpegTask(
            inputs={video.message_data.file_path: None},
            outputs={new_path: f"-filter:v \"setpts=PTS/{speed}\" -filter:a \"atempo={speed}\""},
        )
        await self.worker.await_task(task)
        return new_path
