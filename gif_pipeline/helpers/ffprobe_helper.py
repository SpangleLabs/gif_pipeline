from typing import Optional, List

from gif_pipeline.group import Group
from gif_pipeline.helpers.helpers import Helper, find_video_for_message
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmprobe_task import FFprobeTask


class FFProbeHelper(Helper):
    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        # If a message has text saying ffprobe or stats, and is a reply to a video, get stats for that video
        clean_text = message.text.strip().lower()
        if clean_text.startswith("ffprobe") or clean_text.startswith("stats"):
            video = find_video_for_message(chat, message)
            if video is not None:
                async with self.progress_message(chat, message, "Getting video stats"):
                    stats = await self.stats_for_video(video.message_data.file_path)
                    stats_reply = await self.send_text_reply(chat, message, stats)
                return [stats_reply]
            reply = await self.send_text_reply(
                chat,
                message,
                "Cannot work out which video you want stats about. "
                "Please reply to the video you want to get stats for with the message \"ffprobe\"."
            )
            return [reply]
        if clean_text.startswith("duration"):
            video = find_video_for_message(chat, message)
            if video is not None:
                async with self.progress_message(chat, message, "Getting video duration"):
                    duration = await self.duration_video(video.message_data.file_path)
                    stats_reply = await self.send_text_reply(chat, message, f"{duration} seconds")
                return [stats_reply]
            reply = await self.send_text_reply(
                chat,
                message,
                "Cannot work out which video you want the duration of. "
                "Please reply to the video you want to know the duration of with the message \"duration\"."
            )
            return [reply]
        # Otherwise, ignore
        return

    async def stats_for_video(self, video_path: str) -> str:
        probe_task = FFprobeTask(
            global_options=["-v error -show_format -show_streams "],
            inputs={video_path: ""}
        )
        return await self.worker.await_task(probe_task)

    async def duration_video(self, video_path: str) -> float:
        probe_task = FFprobeTask(
            global_options=["-v error"],
            inputs={video_path: "-show_entries format=duration -of default=noprint_wrappers=1:nokey=1"}
        )
        return float(await self.worker.await_task(probe_task))
