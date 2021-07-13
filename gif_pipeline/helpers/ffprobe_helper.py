from typing import Optional, List, Tuple

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, find_video_for_message
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmprobe_task import FFprobeTask


class FFProbeHelper(Helper):
    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        # If a message has text saying ffprobe or stats, and is a reply to a video, get stats for that video
        clean_text = message.text.strip().lower()
        video = find_video_for_message(chat, message)
        if clean_text.startswith("ffprobe") or clean_text.startswith("stats"):
            if video is not None:
                async with self.progress_message(chat, message, "Getting video stats"):
                    stats = await self.stats_for_video(video.message_data.file_path)
                    return [await self.send_text_reply(chat, message, stats)]
            return [await self.send_text_reply(
                chat,
                message,
                "Cannot work out which video you want stats about. "
                "Please reply to the video you want to get stats for with the message \"ffprobe\"."
            )]
        if clean_text.startswith("duration"):
            if video is not None:
                async with self.progress_message(chat, message, "Getting video duration"):
                    duration = await self.duration_video(video.message_data.file_path)
                    return [await self.send_text_reply(chat, message, f"{duration} seconds")]
            return [await self.send_text_reply(
                chat,
                message,
                "Cannot work out which video you want the duration of. "
                "Please reply to the video you want to know the duration of with the message \"duration\"."
            )]
        if clean_text.startswith("resolution") or clean_text.startswith("size"):
            if video is not None:
                async with self.progress_message(chat, message, "Getting video resolution"):
                    resolution = await self.video_resolution(video.message_data.file_path)
                    return [await self.send_text_reply(chat, message, f"{resolution[0]} x {resolution[1]}")]
            return [await self.send_text_reply(
               chat,
               message,
               "Cannot work out which video you want the resolution of."
               "Please reply to the video you want to know the resolution of with the message \"resolution\"."
            )]
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
    
    async def video_resolution(self, video_path: str) -> Tuple[int, int]:
        probe_task = FFprobeTask(
            global_options=["-v error"],
            inputs={video_path: "-show_entries stream=width,height -of csv=p=0:s=x"}
        )
        resolution_str = await self.worker.await_task(probe_task)
        resolution_split = resolution_str.split("x")
        return int(resolution_split[0]), int(resolution_split[1])
