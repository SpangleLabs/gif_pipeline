from typing import Optional, List

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.message import Message
from gif_pipeline.tasks.update_youtube_dl_task import UpdateYoutubeDLTask
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


class UpdateYoutubeDlHelper(Helper):

    def __init__(self, database: Database, client: TelegramClient, worker: TaskWorker):
        super().__init__(database, client, worker)

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        names = ["downloader"]
        names += [
            fmt.format(yt, dl)
            for fmt in ["{} {}", "{}-{}"]
            for yt in ["youtube", "yt"]
            for dl in ["dl", "download", "dlp", "downloader"]
        ]
        cmds = [f"update {name}" for name in names]
        if not any(message.text.lower().strip().startswith(cmd) for cmd in cmds):
            return
        self.usage_counter.inc()
        async with self.progress_message(chat, message, "Updating youtube downloader"):
            resp = await self.worker.await_task(UpdateYoutubeDLTask())
            return [
                await self.send_text_reply(chat, message, f"Youtube downloader update returned: {resp}")
            ]
