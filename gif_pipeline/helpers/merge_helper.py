import asyncio
import shutil
from typing import List, Optional, Tuple

from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper, random_sandbox_video_path
from gif_pipeline.helpers.video_helper import add_audio_track_task, video_has_audio_track_task
from gif_pipeline.message import Message
from gif_pipeline.tasks.ffmpeg_task import FfmpegTask
from gif_pipeline.tasks.ffmprobe_task import FFprobeTask


class MergeHelper(Helper):
    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        text_clean = message.message_data.text.lower().strip()
        if text_clean.startswith("merge"):
            self.usage_counter.inc()
            merge_command = text_clean[5:].strip()
            return await self.handle_merge(chat, message, merge_command)
        if text_clean.startswith("append"):
            self.usage_counter.inc()
            append_command = text_clean[6:]
            return await self.handle_append(chat, message, append_command)
        if text_clean.startswith("prepend"):
            self.usage_counter.inc()
            prepend_command = text_clean[7:]
            return await self.handle_prepend(chat, message, prepend_command)
        return None

    async def handle_merge(self, chat: Chat, message: Message, merge_command: str) -> Optional[List[Message]]:
        messages_to_merge = []
        reply_to = chat.message_by_id(message.message_data.reply_to)
        if reply_to is not None:
            if not reply_to.has_video:
                error_text = "Cannot merge the message you're replying to, as it doesn't have a video."
                return [await self.send_text_reply(chat, message, error_text)]
            messages_to_merge.append(reply_to)
        links = merge_command.split()
        for link in links:
            msg = chat.message_by_link(link)
            if msg is None:
                error_text = f"Cannot find message for link: {link}"
                return [await self.send_text_reply(chat, message, error_text)]
            if not msg.has_video:
                error_text = f"Cannot merge linked message, {link} , as it has no video"
                return [await self.send_text_reply(chat, message, error_text)]
            messages_to_merge.append(msg)
        return await self.merge_messages(chat, message, messages_to_merge)

    async def handle_append(self, chat: Chat, message: Message, append_command: str) -> Optional[List[Message]]:
        messages_to_merge = []
        reply_to = chat.message_by_id(message.message_data.reply_to)
        if reply_to is None:
            error_text = "The append command needs to be in reply to another message."
            return [await self.send_text_reply(chat, message, error_text)]
        if not reply_to.has_video:
            error_text = "Cannot append to the message you're replying to, as it doesn't have a video."
            return [await self.send_text_reply(chat, message, error_text)]
        messages_to_merge.append(reply_to)
        links = append_command.split()
        for link in links:
            msg = chat.message_by_link(link)
            if msg is None:
                error_text = f"Cannot find message for link: {link}"
                return [await self.send_text_reply(chat, message, error_text)]
            if not msg.has_video:
                error_text = f"Cannot append linked message, {link} , as it has no video"
                return [await self.send_text_reply(chat, message, error_text)]
            messages_to_merge.append(msg)
        return await self.merge_messages(chat, message, messages_to_merge)

    async def handle_prepend(self, chat: Chat, message: Message, prepend_command: str) -> Optional[List[Message]]:
        messages_to_merge = []
        links = prepend_command.split()
        for link in links:
            msg = chat.message_by_link(link)
            if msg is None:
                error_text = f"Cannot find message for link: {link}"
                return [await self.send_text_reply(chat, message, error_text)]
            if not msg.has_video:
                error_text = f"Cannot prepend linked message, {link} , as it has no video"
                return [await self.send_text_reply(chat, message, error_text)]
            messages_to_merge.append(msg)
        reply_to = chat.message_by_id(message.message_data.reply_to)
        if reply_to is None:
            error_text = "The prepend command needs to be in reply to another message."
            return [await self.send_text_reply(chat, message, error_text)]
        if not reply_to.has_video:
            error_text = "Cannot merge the message you're replying to, as it doesn't have a video."
            return [await self.send_text_reply(chat, message, error_text)]
        messages_to_merge.append(reply_to)
        return await self.merge_messages(chat, message, messages_to_merge)

    async def merge_messages(
            self,
            chat: Chat,
            cmd_message: Message,
            messages_to_merge: List[Message]
    ) -> Optional[List[Message]]:
        if len(messages_to_merge) < 2:
            error_text = \
                "Merge commands require at least 2 videos to merge. " \
                "Please reply to a message, and provide telegram links to the other messages"
            return [await self.send_text_reply(chat, cmd_message, error_text)]
        num_files = len(messages_to_merge)
        filter_args = "".join([f"[{x}:v][{x}:a]" for x in range(num_files)]) + f" concat=n={num_files}:v=1:a=1 [v] [a]"
        output_args = f"-filter_complex \"{filter_args}\" -map \"[v]\" -map \"[a]\" -vsync 2"
        async with self.progress_message(chat, cmd_message, "Merging videos"):
            file_paths = await self.align_video_dimensions([m.message_data.file_path for m in messages_to_merge])
            output_path = random_sandbox_video_path()
            task = FfmpegTask(
                inputs={file_path: None for file_path in file_paths},
                outputs={output_path: output_args}
            )
            await self.worker.await_task(task)
            tags = messages_to_merge[0].tags(self.database)
            tags.merge_all([msg.tags(self.database) for msg in messages_to_merge[1:]])
            return [await self.send_video_reply(chat, cmd_message, output_path, tags)]

    async def align_video_dimensions(self, file_paths: List[str]) -> List[str]:
        first = file_paths[0]
        the_rest = file_paths[1:]
        # Get dimensions of first video, scale the rest to match
        dimensions = await self.get_video_dimensions(first)
        rescaled = await asyncio.gather(*[self.scale_and_pad_to_dimensions(path, dimensions) for path in the_rest])
        same_dimension_paths = [first] + rescaled
        # Add audio tracks if necessary
        with_audio = await asyncio.gather(*[self.with_audio_track(path) for path in same_dimension_paths])
        # Handle duplicate file paths. Copy them to sandbox files
        output_paths = []
        for path in with_audio:
            if path in output_paths:
                new_path = random_sandbox_video_path(path.split(".")[-1])
                shutil.copyfile(path, new_path)
                output_paths.append(new_path)
            else:
                output_paths.append(path)
        return output_paths

    async def get_video_dimensions(self, file_path: str) -> Tuple[int, int]:
        task = FFprobeTask(
            inputs={file_path: "-v error -show_entries stream=width,height -of csv=p=0:s=x"}
        )
        return tuple((await self.worker.await_task(task)).split("x"))

    async def scale_and_pad_to_dimensions(self, file_path: str, dimensions: Tuple[int, int]) -> str:
        orig_dimensions = await self.get_video_dimensions(file_path)
        if orig_dimensions == dimensions:
            return file_path
        output_path = random_sandbox_video_path()
        x, y = dimensions
        args = f"-vf \"scale={x}:{y}:force_original_aspect_ratio=decrease,pad={x}:{y}:(ow-iw)/2:(oh-ih)/2,setsar=1\""
        task = FfmpegTask(
            inputs={file_path: None},
            outputs={output_path: args}
        )
        await self.worker.await_task(task)
        return output_path

    async def with_audio_track(self, file_path: str) -> str:
        audio_check_task = video_has_audio_track_task(file_path)
        if not await self.worker.await_task(audio_check_task):
            output_path = random_sandbox_video_path()
            await self.worker.await_task(add_audio_track_task(file_path, output_path))
            return output_path
        return file_path
