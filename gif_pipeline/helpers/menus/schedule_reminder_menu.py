import random
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Dict, List, Optional, Set

import dateutil.parser
from telethon import Button

from gif_pipeline.helpers.menus.menu import Menu

if TYPE_CHECKING:
    from gif_pipeline.chat import Channel, Chat
    from gif_pipeline.helpers.menu_helper import MenuHelper
    from gif_pipeline.helpers.send_helper import GifSendHelper
    from gif_pipeline.message import Message
    from gif_pipeline.tag_manager import TagManager


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
    callback_auto_post = b"auto_post"
    callback_send_now = b"send_now"

    def __init__(
            self,
            menu_helper: 'MenuHelper',
            chat: 'Chat',
            cmd: None,
            video: 'Message',
            post_time: datetime,
            channel: 'Channel',
            tag_manager: 'TagManager',
            send_helper: 'GifSendHelper',
            auto_post: bool = False
    ):
        super().__init__(menu_helper, chat, cmd, video)
        self.post_time = post_time
        self.channel = channel
        self.tag_manager = tag_manager
        self.send_helper = send_helper
        self.auto_post = auto_post

    @property
    def text(self) -> str:
        time_str = self.post_time.strftime("%Y-%m-%d at %H:%M (UTC)")
        now = datetime.now(timezone.utc)
        if self.post_time.date() == now.date():
            time_str = f"today at {self.post_time.strftime('%H:%M')} (UTC)"
        tags_str = ""
        if self.missing_tags:
            tags_str = (
                "\nHowever, it is currently missing these tags: \n" +
                "\n".join("- "+tag for tag in self.missing_tags)
            )
        return f"I am planning to post this video at {time_str}.{tags_str}"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        auto_post_str = "{} auto post and remove".format("✔️" if self.auto_post else "❌")
        buttons = [
            [Button.inline("🎲 Re-roll", self.callback_re_roll)],
            [Button.inline("Send now", self.callback_send_now)],
            [Button.inline(auto_post_str, self.callback_auto_post)]
        ]
        return buttons

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
            self.auto_post = False
            return [await self.send()]
        if callback_query == self.callback_auto_post:
            self.auto_post = not self.auto_post
            return [await self.send()]
        if callback_query == self.callback_send_now:
            return await self.menu_helper.confirmation_menu(
                self.chat, self.cmd, self.video, self.send_helper, self.channel
            )

    @property
    def missing_tags(self) -> Set[str]:
        return self.tag_manager.missing_tags_for_video(self.video, self.channel, self.chat)

    @classmethod
    def json_name(cls) -> str:
        return "schedule_reminder_menu"

    def to_json(self) -> Dict:
        return {
            "post_time": self.post_time.isoformat(),
            "auto_post": self.auto_post
        }

    @classmethod
    def from_json(
            cls,
            json_data: Dict,
            menu_helper: 'MenuHelper',
            chat: 'Chat',
            video: 'Message',
            all_channels: List['Channel'],
            tag_manager: 'TagManager',
            send_helper: 'GifSendHelper',
    ) -> 'Menu':
        destination = next(filter(lambda channel: channel.queue == chat, all_channels), None)
        return ScheduleReminderMenu(
            menu_helper,
            chat,
            None,
            video,
            dateutil.parser.parse(json_data["post_time"]),
            destination,
            tag_manager,
            send_helper,
            json_data.get("auto_post", False)
        )
