from datetime import datetime
from typing import Dict, TYPE_CHECKING, Optional, List

import dateutil.parser
from telethon import Button

from gif_pipeline.helpers.menus.menu import Menu

if TYPE_CHECKING:
    from gif_pipeline.chat import Chat
    from gif_pipeline.helpers.menu_helper import MenuHelper
    from gif_pipeline.message import Message


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
        self.posted = False

    @property
    def text(self) -> str:
        return f"I am planning to post this video at {self.post_time.isoformat()}."

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return None  # TODO
        # return [[Button.inline("🎲 Re-roll", self.callback_reroll)]]

    def allows_sender(self, sender_id: int) -> bool:
        return True

    def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        return None  # TODO
        # if callback_query == self.callback_reroll:

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
