from abc import abstractmethod
import datetime
from typing import Optional, List, Tuple

from scenedetect import FrameTimecode
from telethon import Button

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.helpers.scene_split_helper import SceneSplitHelper
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.menu_cache import MenuCache, SentMenu
from gif_pipeline.message import Message
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient


def delta_to_string(delta: datetime.timedelta) -> str:
    days, remainder = divmod(delta.total_seconds(), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    day_word = "day" if days == 1 else "days"
    hour_word = "hour" if hours == 1 else "hours"
    minute_word = "minute" if minutes == 1 else "minutes"
    if days:
        return f"{days} {day_word}, {hours} {hour_word}"
    return f"{hours} {hour_word}, {minutes} {minute_word}"


class MenuHelper(Helper):

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            menu_cache: MenuCache,
    ):
        super().__init__(database, client, worker)
        # Cache of message ID the menu is replying to, to the menu
        self.menu_cache = menu_cache

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        pass

    async def on_callback_query(
            self,
            callback_query: bytes,
            menu: SentMenu
    ) -> Optional[List[Message]]:
        # Prevent double clicking menus
        menu.clicked = True
        resp = await menu.menu.handle_callback_query(callback_query)
        return resp

    async def delete_menu_for_video(self, video: Message) -> None:
        menu = self.menu_cache.get_menu_by_video(video)
        if menu:
            await self.client.delete_message(menu.msg.message_data)
            menu.msg.delete(self.database)
            self.menu_cache.remove_menu_by_video(video)

    async def send_not_gif_warning_menu(
            self,
            chat: Chat,
            cmd: Message,
            video: Message,
            send_helper: GifSendHelper,
            dest_str: str
    ) -> List[Message]:
        menu = NotGifConfirmationMenu(self, chat, cmd, video, send_helper, dest_str)
        menu_msg = await menu.send()
        return [menu_msg]

    async def destination_menu(
            self,
            chat: Chat,
            cmd: Message,
            video: Message,
            send_helper: GifSendHelper,
            channels: List[Channel],
            current_folder: Optional[str] = None
    ) -> List[Message]:
        menu = DestinationMenu(self, chat, cmd, video, send_helper, channels, current_folder)
        menu_msg = await menu.send()
        return [menu_msg]

    async def confirmation_menu(
            self,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination_id: str,
    ) -> List[Message]:
        destination = send_helper.get_destination_from_name(destination_id)
        menu = SendConfirmationMenu(self, chat, cmd_msg, video, send_helper, destination)
        menu_msg = await menu.send()
        return [menu_msg]

    async def after_send_delete_menu(
            self,
            chat: Chat,
            cmd: Message,
            video: Message,
            text: str,
    ) -> Optional[Message]:
        admin_ids = await self.client.list_authorized_to_delete(chat.chat_data)
        if cmd.message_data.sender_id not in admin_ids:
            await self.delete_menu_for_video(video)
            return None
        menu = DeleteMenu(self, chat, cmd, video, text)
        message = await menu.send()
        return message

    async def split_scenes_confirmation(
            self,
            chat: Chat,
            cmd: Message,
            video: Message,
            threshold: int,
            scene_list: List[Tuple[FrameTimecode, FrameTimecode]],
            split_helper: SceneSplitHelper
    ) -> Message:
        menu = SplitScenesConfirmationMenu(self, chat, cmd, video, threshold, scene_list, split_helper)
        message = await menu.send()
        return message


class Menu:

    def __init__(self, menu_helper: MenuHelper, chat: Chat, cmd: Message, video: Message):
        self.menu_helper = menu_helper
        self.chat = chat
        self.cmd = cmd
        self.video = video

    def add_self_to_cache(self, menu_msg: Message):
        self.menu_helper.menu_cache.add_menu(SentMenu(self, menu_msg))

    @property
    def owner_id(self) -> int:
        return self.cmd.message_data.sender_id

    @property
    @abstractmethod
    def text(self) -> str:
        pass

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return None

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        pass

    async def send_as_reply(self, reply_to: Message) -> Message:
        menu_msg = await self.menu_helper.send_text_reply(
            self.chat,
            reply_to,
            self.text,
            buttons=self.buttons
        )
        self.add_self_to_cache(menu_msg)
        return menu_msg

    async def edit_message(self, old_msg: Message) -> Message:
        menu_msg = await self.menu_helper.edit_message(
            self.chat,
            old_msg,
            new_text=self.text,
            new_buttons=self.buttons
        )
        if self.buttons:
            self.add_self_to_cache(menu_msg)
        else:
            self.menu_helper.menu_cache.remove_menu_by_video(self.video)
        return menu_msg

    async def send(self) -> Message:
        menu = self.menu_helper.menu_cache.get_menu_by_video(self.video)
        if menu:
            return await self.edit_message(menu.msg)
        return await self.send_as_reply(self.video)

    async def delete(self) -> None:
        await self.menu_helper.delete_menu_for_video(self.video)


class NotGifConfirmationMenu(Menu):
    clear_menu = b"clear_not_gif_menu"
    send_str = "send_str"

    def __init__(
            self,
            menu_helper: MenuHelper,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            dest_str: str
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.dest_str = dest_str

    @property
    def text(self) -> str:
        return "It looks like this video has not been giffed. Are you sure you want to send it?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        button_data = f"{self.send_str}:{self.dest_str}"
        return [
            [Button.inline("Yes, I am sure", button_data)],
            [Button.inline("No thanks!", self.clear_menu)]
        ]

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.clear_menu:
            await self.delete()
            return []
        # Handle sending if the user is sure
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.send_str:
            _, dest_str = split_data
            return await self.send_helper.handle_dest_str(
                self.chat, self.cmd, self.video, dest_str, self.owner_id
            )


class DestinationMenu(Menu):
    confirm_send = "confirm_send"
    folder = "send_folder"

    def __init__(
            self,
            menu_helper: MenuHelper,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            channels: List[Channel],
            current_folder: Optional[str]
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.channels = channels
        self.current_folder = current_folder

    @property
    def text(self) -> str:
        return "Which channel should this video be sent to?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        buttons = []
        folders = set()
        channels = set()
        for channel in self.channels:
            if channel.config.send_folder is None:
                if self.current_folder is None:
                    channels.add(channel)
            else:
                if self.current_folder is None:
                    folders.add(channel.config.send_folder.split("/")[0])
                else:
                    if channel.config.send_folder == self.current_folder:
                        channels.add(channel)
                    if channel.config.send_folder.startswith(self.current_folder + "/"):
                        folders.add(channel.config.send_folder[len(self.current_folder + "/"):].split("/")[0])
        # Create folder buttons
        for folder in sorted(folders):
            buttons.append(Button.inline(
                "📂: " + folder,
                f"{self.folder}:{folder}"
            ))
        # Create channel buttons
        for channel in sorted(channels, key=lambda chan: chan.chat_data.title):
            buttons.append(Button.inline(
                channel.chat_data.title,
                f"{self.confirm_send}:{channel.chat_data.chat_id}"
            ))
        # Create back button
        if self.current_folder is not None:
            buttons.append(Button.inline(
                "🔙 Back",
                f"{self.folder}:/"
            ))
        return [[b] for b in buttons]

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.confirm_send:
            destination_id = split_data[1]
            return await self.menu_helper.confirmation_menu(
                self.chat, self.cmd, self.video, self.send_helper, destination_id
            )
        if split_data[0] == self.folder:
            next_folder = split_data[1]
            if next_folder == "/":
                if self.current_folder is None or "/" not in self.current_folder:
                    folder = None
                else:
                    folder = "/".join(self.current_folder.split("/")[:-1])
            else:
                folder = next_folder
                if self.current_folder is not None:
                    folder = self.current_folder + "/" + next_folder
            return await self.menu_helper.destination_menu(
                self.chat, self.cmd, self.video, self.send_helper, self.channels, folder
            )


class SendConfirmationMenu(Menu):
    clear_confirm_menu = b"clear_menu"
    send_callback = b"send"

    def __init__(
            self,
            menu_helper: MenuHelper,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
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
                now = self.cmd.message_data.datetime
                duration = now - last_post.message_data.datetime
                duration_str = delta_to_string(duration)
                msg += f"\nThe last post there was {duration_str} ago"
        return msg

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return [
            [Button.inline("I am sure", self.send_callback)],
            [Button.inline("No thanks", self.clear_confirm_menu)]
        ]

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.clear_confirm_menu:
            await self.delete()
            return []
        if callback_query == self.send_callback:
            return await self.send_helper.send_video(
                self.chat, self.video, self.cmd, self.destination, self.owner_id
            )


class DeleteMenu(Menu):
    def __init__(self, menu_helper: MenuHelper, chat: Chat, cmd_msg: Message, video: Message, prefix_str: str):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.prefix_str = prefix_str
        self.cleared = False

    @property
    def text(self):
        if self.cleared:
            return self.prefix_str
        return self.prefix_str + "\nWould you like to delete the message family?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        if self.cleared:
            return None
        return [
            [Button.inline("Yes please", f"delete:{self.video.message_data.message_id}")],
            [Button.inline("No thanks", f"clear_delete_menu")]
        ]

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == "clear_delete_menu":
            self.cleared = True
            sent_msg = await self.send()
            return [sent_msg]
        # The "delete:" callback is handled by DeleteHelper


class SplitScenesConfirmationMenu(Menu):
    cmd_split = b"split"
    cmd_cancel = b"split_clear_menu"

    def __init__(
            self,
            menu_helper: MenuHelper,
            chat: Chat,
            cmd: Message,
            video: Message,
            threshold: int,
            scene_list: List[Tuple[FrameTimecode, FrameTimecode]],
            split_helper: SceneSplitHelper
    ):
        super().__init__(menu_helper, chat, cmd, video)
        self.threshold = threshold
        self.scene_list = scene_list
        self.split_helper = split_helper
        self.cleared = False

    @property
    def text(self) -> str:
        scene_count = len(self.scene_list)
        if not self.cleared:
            return f"Using a threshold of {self.threshold}, this video would be split into {scene_count} scenes. " \
               f"Would you like to proceed with cutting?"
        return f"Using a threshold of {self.threshold}, this video would have been split into {scene_count} scenes."

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        if not self.cleared:
            return [
                [Button.inline("Yes please", self.cmd_split)],
                [Button.inline("No thank you", self.cmd_cancel)]
            ]

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.cmd_cancel:
            self.cleared = True
            sent_msg = await self.send()
            return [sent_msg]
        if callback_query == self.cmd_split:
            await self.delete()
            progress_text = f"Splitting video into {len(self.scene_list)} scenes"
            async with self.menu_helper.progress_message(self.chat, self.cmd, progress_text):
                return await self.split_helper.split_scenes(self.chat, self.cmd, self.video, self.scene_list)
