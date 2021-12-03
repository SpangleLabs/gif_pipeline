from typing import TYPE_CHECKING, Optional, List

import matplotlib.pyplot as plt

from gif_pipeline.helpers.helpers import Helper, random_sandbox_video_path

if TYPE_CHECKING:
    from gif_pipeline.chat import Chat
    from gif_pipeline.database import Database
    from gif_pipeline.message import Message
    from gif_pipeline.pipeline import Pipeline
    from gif_pipeline.tag_manager import TagManager
    from gif_pipeline.tasks.task_worker import TaskWorker
    from telethon import TelegramClient


class ChartHelper(Helper):

    def __init__(
            self,
            database: "Database",
            client: "TelegramClient",
            worker: "TaskWorker",
            pipeline: "Pipeline",
            tag_manager: "TagManager"
    ):
        super().__init__(database, client, worker)
        self.pipeline = pipeline
        self.tag_manager = tag_manager

    async def on_new_message(self, chat: "Chat", message: "Message") -> Optional[List["Message"]]:
        split_text = message.text.split()
        if not split_text or split_text[0].lower() != "chart":
            return None
        target_chat = self.pipeline.channel_by_handle(split_text[1])
        if target_chat is None:
            return [await self.send_text_reply(
                chat,
                message,
                "Unrecognised chat. Command format: chart {destination} {tag_name}"
            )]
        tag_name = split_text[2]
        counter = self.tag_manager.tag_value_rates_for_chat(target_chat, tag_name)
        counter_tuples = counter.most_common()
        values = [t[0] for t in counter_tuples]
        keys = [f"{t[1]} ({t[0]})" for t in counter_tuples]
        plt.pie(values, labels=keys)
        plt.legend()
        filename = random_sandbox_video_path("png")
        plt.savefig(filename)
        return [await self.send_message(
            chat,
            reply_to_msg=message,
            video_path=filename,
            text=f"Pie chart of tag values for {tag_name} in {target_chat.chat_data.title}"
        )]
