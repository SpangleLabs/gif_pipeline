import asyncio
import mimetypes
import zipfile
from typing import Optional, List

from group import Group
from helpers.helpers import Helper, random_sandbox_video_path
from message import Message, mime_type_is_video


class ZipHelper(Helper):
    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        if message.message_data.has_file and message.message_data.file_path.endswith(".zip"):
            results = await self.unzip(chat, message)
            if results:
                return results
            return [await self.send_text_reply(chat, message, "This zip file contained no video files.")]

    async def unzip(self, chat: Group, message: Message) -> Optional[List[Message]]:
        video_paths = []
        with zipfile.ZipFile(message.message_data.file_path, "r") as zip_ref:
            for filename in zip_ref.namelist():
                mime_type, _ = mimetypes.guess_type(filename)
                if mime_type_is_video(mime_type):
                    file_ext = filename.split(".")[-1]
                    video_path = random_sandbox_video_path(file_ext)
                    zip_ref.extract(filename, video_path)
                    video_paths.append(video_path)
        if video_paths:
            return await asyncio.gather(*[self.send_video_reply(chat, message, path) for path in video_paths])
        return None
