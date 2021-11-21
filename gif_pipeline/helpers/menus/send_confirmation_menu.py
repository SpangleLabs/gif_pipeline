from datetime import timezone, datetime
from typing import Optional, List, TYPE_CHECKING, Dict

from telethon import Button

from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.menus.menu import Menu, delta_to_string
from gif_pipeline.message import Message

if TYPE_CHECKING:
    from gif_pipeline.helpers.send_helper import GifSendHelper
    from gif_pipeline.helpers.menu_helper import MenuHelper


class SendConfirmationMenu(Menu):
    clear_confirm_menu = b"clear_menu"
    send_callback = b"send"
    send_queue = b"queue"

    def __init__(
            self,
            menu_helper: 'MenuHelper',
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: 'GifSendHelper',
            destination: Channel
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.destination = destination

    @property
    def text(self) -> str:
        msg = f"Are you sure you want to send this video to {self.destination.chat_data.title}?"
        if self.destination.config.note_time:
            last_post = self.destination.latest_message()
            if last_post is None:
                msg += "There have been no posts there yet."
            else:
                now = datetime.now(timezone.utc)
                duration = now - last_post.message_data.datetime
                duration_str = delta_to_string(duration)
                msg += f"\nThe last post there was {duration_str} ago"
        if self.destination.has_queue:
            queue_count = self.destination.queue.count_videos()
            msg += f"\nThere are {queue_count} videos in the queue"
        return msg

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        buttons = [
            [Button.inline("I am sure", self.send_callback)],
        ]
        if self.destination.has_queue:
            buttons.append(
                [Button.inline("Send to queue", self.send_queue)]
            )
        buttons.append(
            [Button.inline("No thanks", self.clear_confirm_menu)]
        )
        return buttons

    async def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int,
    ) -> Optional[List[Message]]:
        if callback_query == self.clear_confirm_menu:
            await self.delete()
            return []
        if callback_query == self.send_callback:
            return await self.send_helper.send_video(
                self.chat, self.video, self.cmd, self.destination, sender_id
            )
        if callback_query == self.send_queue:
            return await self.send_helper.send_video(
                self.chat, self.video, self.cmd, self.destination.queue, sender_id
            )

    @classmethod
    def json_name(cls) -> str:
        return "send_confirmation_menu"

    def to_json(self) -> Dict:
        return {
            "cmd_msg_id": self.cmd_msg_id,
            "destination_id": self.destination.chat_data.chat_id
        }

    @classmethod
    def from_json(
            cls,
            json_data: Dict,
            menu_helper: 'MenuHelper',
            chat: Chat,
            video: Message,
            send_helper: 'GifSendHelper',
            all_channels: List[Channel]
    ) -> 'Menu':
        destination = next(filter(lambda x: x.chat_data.chat_id == json_data["destination_id"], all_channels), None)
        return SendConfirmationMenu(
            menu_helper,
            chat,
            chat.message_by_id(json_data["cmd_msg_id"]),
            video,
            send_helper,
            destination
        )
