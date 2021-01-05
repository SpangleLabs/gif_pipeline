from abc import abstractmethod
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple

from scenedetect import FrameTimecode
from telethon import Button

from database import Database
from group import Group, Channel
from helpers.helpers import Helper
from helpers.scene_split_helper import SceneSplitHelper
from helpers.send_helper import GifSendHelper
from menu_cache import MenuOwnershipCache
from message import Message
from tasks.task_worker import TaskWorker
from telegram_client import TelegramClient


class MenuHelper(Helper):

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            menu_ownership_cache: MenuOwnershipCache,
    ):
        super().__init__(database, client, worker)
        # Cache of message ID the menu is replying to, to the menu
        # TODO: save and load menu cache, so that menus can resume when bot reboots
        self.menu_cache: Dict[int, Dict[int, SentMenu]] = defaultdict(lambda: {})
        # TODO: eventually remove this class, when MenuHelper is handling all menus
        self.menu_ownership_cache: MenuOwnershipCache = menu_ownership_cache

    async def on_new_message(self, chat: Group, message: Message) -> Optional[List[Message]]:
        pass

    def add_menu_to_cache(self, sent_menu: 'SentMenu') -> None:
        self.menu_cache[
            sent_menu.menu.video.chat_data.chat_id
        ][
            sent_menu.menu.video.message_data.message_id
        ] = sent_menu
        self.menu_ownership_cache.add_menu_msg(sent_menu.msg, sent_menu.menu.owner_id)

    def get_menu_from_cache(self, video: Message) -> Optional['SentMenu']:
        return self.menu_cache.get(video.chat_data.chat_id, {}).get(video.message_data.message_id)

    async def delete_menu_for_video(self, video: Message) -> None:
        menu = self.get_menu_from_cache(video)
        if menu:
            await self.client.delete_message(menu.msg.message_data)
            menu.msg.delete(self.database)
            self.remove_menu_from_cache(video)

    def remove_menu_from_cache(self, video: Message) -> None:
        menu = self.get_menu_from_cache(video)
        if menu:
            del self.menu_cache[video.chat_data.chat_id][video.message_data.message_id]
            self.menu_ownership_cache.remove_menu_msg(menu.msg)

    def get_menu_by_message_id(self, chat_id: int, menu_msg_id: int) -> Optional['SentMenu']:
        menus = [
            menu for video_id, menu in self.menu_cache.get(chat_id, {}).items()
            if menu.msg.message_data.message_id == menu_msg_id
        ]
        return next(iter(menus), None)

    async def on_callback_query(
            self, chat: Group, callback_query: bytes, sender_id: int, menu_msg_id: int
    ) -> Optional[List[Message]]:
        # Menus are cached by video ID, not menu message ID.
        menu = self.get_menu_by_message_id(chat.chat_data.chat_id, menu_msg_id)
        if menu and not menu.clicked:
            # Prevent double clicking menus
            menu.clicked = True
            return await menu.menu.handle_callback_query(callback_query, sender_id)
        # TODO: When MenuHelper is handling all menus, throw an error message here for menu not existing

    async def send_not_gif_warning_menu(
            self,
            chat: Group,
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
            chat: Group,
            cmd: Message,
            video: Message,
            send_helper: GifSendHelper,
            channels: List[Channel]
    ) -> List[Message]:
        menu = DestinationMenu(self, chat, cmd, video, send_helper, channels)
        menu_msg = await menu.send()
        return [menu_msg]

    async def confirmation_menu(
            self,
            chat: Group,
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
            chat: Group,
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
            chat: Group,
            cmd: Message,
            video: Message,
            threshold: int,
            scene_list: List[Tuple[FrameTimecode, FrameTimecode]],
            split_helper: SceneSplitHelper
    ) -> Message:
        menu = SplitScenesConfirmationMenu(self, chat, cmd, video, threshold, scene_list, split_helper)
        message = await menu.send()
        return message


@dataclass
class SentMenu:
    menu: 'Menu'
    msg: Message
    clicked: bool = False


class Menu:

    def __init__(self, menu_helper: MenuHelper, chat: Group, cmd: Message, video: Message):
        self.menu_helper = menu_helper
        self.chat = chat
        self.cmd = cmd
        self.video = video

    def add_self_to_cache(self, menu_msg: Message):
        self.menu_helper.add_menu_to_cache(SentMenu(self, menu_msg))

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
            callback_query: bytes,
            sender_id: int
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
            self.menu_helper.remove_menu_from_cache(self.video)
        return menu_msg

    async def send(self) -> Message:
        menu = self.menu_helper.get_menu_from_cache(self.video)
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
            chat: Group,
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
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        if callback_query == self.clear_menu:
            await self.delete()
            return []
        # Handle sending if the user is sure
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.send_str:
            _, dest_str = split_data
            return await self.send_helper.handle_dest_str(
                self.chat, self.cmd, self.video, dest_str, sender_id
            )


class DestinationMenu(Menu):
    confirm_send = "confirm_send"

    def __init__(
            self,
            menu_helper: MenuHelper,
            chat: Group,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            channels: List[Channel]
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.channels = channels

    @property
    def text(self) -> str:
        return "Which channel should this video be sent to?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return [
            [Button.inline(
                channel.chat_data.title,
                f"{self.confirm_send}:{channel.chat_data.chat_id}"
            )]
            for channel in self.channels
        ]

    async def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        split_data = callback_query.decode().split(":")
        if split_data[0] == self.confirm_send:
            destination_id = split_data[1]
            return await self.menu_helper.confirmation_menu(
                self.chat, self.cmd, self.video, self.send_helper, destination_id
            )


class SendConfirmationMenu(Menu):
    clear_confirm_menu = b"clear_menu"
    send_callback = b"send"

    def __init__(
            self,
            menu_helper: MenuHelper,
            chat: Group,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Group
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.destination = destination

    @property
    def text(self) -> str:
        return f"Are you sure you want to send this video to {self.destination.chat_data.title}?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return [
            [Button.inline("I am sure", self.send_callback)],
            [Button.inline("No thanks", self.clear_confirm_menu)]
        ]

    async def handle_callback_query(
            self,
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        if callback_query == self.clear_confirm_menu:
            await self.delete()
            return []
        if callback_query == self.send_callback:
            return await self.send_helper.send_video(
                self.chat, self.video, self.cmd, self.destination, sender_id
            )


class DeleteMenu(Menu):
    def __init__(self, menu_helper: MenuHelper, chat: Group, cmd_msg: Message, video: Message, prefix_str: str):
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
            callback_query: bytes,
            sender_id: int
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
            chat: Group,
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
            callback_query: bytes,
            sender_id: int
    ) -> Optional[List[Message]]:
        if callback_query == self.cmd_cancel:
            self.cleared = True
            return
        if callback_query != self.cmd_split:
            return None
        await self.delete()
        progress_text = f"Splitting video into {len(self.scene_list)} scenes"
        async with self.menu_helper.progress_message(self.chat, self.cmd, progress_text):
            return await self.split_helper.split_scenes(self.chat, self.cmd, self.video, self.scene_list)
