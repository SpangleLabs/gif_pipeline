from datetime import datetime, timezone
import random
from typing import Dict, TYPE_CHECKING, Optional, List

import dateutil.parser
from telethon import Button

from gif_pipeline.helpers.menus.menu import Menu

if TYPE_CHECKING:
    from gif_pipeline.chat import Chat
    from gif_pipeline.helpers.menu_helper import MenuHelper
    from gif_pipeline.message import Message


def next_video_from_list(messages: List['Message']) -> Optional['Message']:
    video = None
    for message in messages:
        if not message.has_video:
            continue
        video = message
        break
    return video

class ScheduleReminderMenu(Menu):
    callback_re_roll = b"re-roll"

    def __init__(
            self,
            menu_helper: 'MenuHelper',
            chat: 'Chat',
            cmd: None,
            video: 'Message',
            post_time: datetime
    ):
        super().__init__(menu_helper, chat, cmd, video)
        self.post_time = post_time

    @property
    def text(self) -> str:
        time_str = self.post_time.strftime("%Y-%m-%d at %H:%M (UTC)")
        now = datetime.now(timezone.utc)
        if self.post_time.date() == now.date():
            time_str = f"today at {self.post_time.strftime('%H:%M')} (UTC)"
        return f"I am planning to post this video at {time_str}."

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return [[Button.inline("🎲 Re-roll", self.callback_re_roll)]]

    def allows_sender(self, sender_id: int) -> bool:
        return True

    async def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List['Message']]:
        if callback_query == self.callback_re_roll:
            messages = random.sample(self.chat.messages, k=len(self.chat.messages))
            new_video = next_video_from_list(messages)
            await self.delete()
            self.video = new_video
            return [await self.send()]

    @classmethod
    def json_name(cls) -> str:
        return "schedule_reminder_menu"

    def to_json(self) -> Dict:
        return {
            "post_time": self.post_time.isoformat()
        }

    @classmethod
    def from_json(
            cls,
            json_data: Dict,
            menu_helper: 'MenuHelper',
            chat: 'Chat',
            video: 'Message'
    ) -> 'Menu':
        return ScheduleReminderMenu(
            menu_helper,
            chat,
            None,
            video,
            dateutil.parser.parse(json_data["post_time"])
        )
