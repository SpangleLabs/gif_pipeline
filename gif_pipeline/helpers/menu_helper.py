from abc import abstractmethod
import datetime
from typing import Optional, List, Tuple, Set

from scenedetect import FrameTimecode
from telethon import Button

from gif_pipeline.database import Database
from gif_pipeline.chat import Chat, Channel
from gif_pipeline.helpers.helpers import Helper
from gif_pipeline.helpers.scene_split_helper import SceneSplitHelper
from gif_pipeline.helpers.send_helper import GifSendHelper
from gif_pipeline.menu_cache import MenuCache, SentMenu
from gif_pipeline.message import Message
from gif_pipeline.tag_manager import TagManager
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
        return f"{days:.0f} {day_word}, {hours:.0f} {hour_word}"
    return f"{hours:.0f} {hour_word}, {minutes:.0f} {minute_word}"


class MenuHelper(Helper):

    def __init__(
            self,
            database: Database,
            client: TelegramClient,
            worker: TaskWorker,
            menu_cache: MenuCache,
            tag_manager: TagManager,
    ):
        super().__init__(database, client, worker)
        # Cache of message ID the menu is replying to, to the menu
        self.menu_cache = menu_cache
        self.tag_manager = tag_manager

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

    async def additional_tags_menu(
            self,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
            missing_tags: Set[str]
    ):
        menu = CheckTagsMenu(self, chat, cmd_msg, video, send_helper, destination, missing_tags)
        menu_msg = await menu.send()
        return [menu_msg]

    async def edit_tag_select(
            self,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
            missing_tags: Set[str]
    ):
        menu = EditTagSelectMenu(self, chat, cmd_msg, video, send_helper, destination, missing_tags)
        menu_msg = await menu.send()
        return [menu_msg]

    async def edit_tag_values(
            self,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
            tag_name: str
    ):
        menu = EditTagValuesMenu(self, chat, cmd_msg, video, send_helper, destination, self.tag_manager, tag_name)
        menu_msg = await menu.send()
        return [menu_msg]

    async def confirmation_menu(
            self,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
    ) -> List[Message]:
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
            destination = self.send_helper.get_destination_from_name(destination_id)
            missing_tags = self.send_helper.missing_tags_for_video(self.video, destination)
            if missing_tags:
                return await self.menu_helper.additional_tags_menu(
                    self.chat, self.cmd, self.video, self.send_helper, destination, missing_tags
                )
            return await self.menu_helper.confirmation_menu(
                self.chat, self.cmd, self.video, self.send_helper, destination
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


class CheckTagsMenu(Menu):
    send_callback = b"send"
    edit_callback = b"edit"
    cancel_callback = b"cancel"

    def __init__(
            self,
            menu_helper: MenuHelper,
            chat: Chat,
            cmd_msg: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
            missing_tags: Set[str]
    ):
        super().__init__(menu_helper, chat, cmd_msg, video)
        self.send_helper = send_helper
        self.destination = destination
        self.missing_tags = missing_tags
        self.cancelled = False

    @property
    def text(self) -> str:
        dest_tags = self.destination.config.tags
        msg = f"The destination suggests videos should be tagged with:\n"
        for tag in dest_tags.keys():
            if tag in self.missing_tags:
                msg += f" - <b>{tag}</b>\n"
            else:
                msg += f" - {tag}\n"
        msg += f"This video is missing {len(self.missing_tags)} tags, bold in the above list"
        return msg

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        if not self.cancelled:
            return [
                [Button.inline("Send anyway", self.send_callback)],
                [Button.inline("Edit tags", self.edit_callback)],
                [Button.inline("Cancel", self.cancel_callback)]
            ]

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.cancel_callback:
            self.cancelled = True
            sent_msg = await self.send()
            return [sent_msg]
        if callback_query == self.edit_callback:
            if len(self.missing_tags) != 1:
                return await self.menu_helper.edit_tag_select(
                    self.chat, self.cmd, self.video, self.send_helper, self.destination, self.missing_tags
                )
            missing_tag_name = next(iter(self.missing_tags))
            return await self.menu_helper.edit_tag_values(
                self.chat, self.cmd, self.video, self.send_helper, self.destination, missing_tag_name
            )
        if callback_query == self.send_callback:
            return await self.menu_helper.confirmation_menu(
                self.chat, self.cmd, self.video, self.send_helper, self.destination
            )


class EditTagSelectMenu(Menu):
    select_callback = b"select"
    cancel_callback = b"cancel"

    def __init__(
            self,
            menu_helper: MenuHelper,
            chat: Chat,
            cmd: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
            missing_tags: Set[str]
    ):
        super().__init__(menu_helper, chat, cmd, video)
        self.send_helper = send_helper
        self.destination = destination
        self.missing_tags = sorted(list(missing_tags))

    @property
    def text(self) -> str:
        return "Which tag would you like to edit?"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        return [
            [Button.inline(tag_name, f"{self.select_callback}:{i}")]
            for i, tag_name in enumerate(self.missing_tags)
        ]

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.cancel_callback:
            await self.delete()
            return []
        if callback_query.startswith(self.select_callback):
            tag_name = self.missing_tags[int(callback_query.split(b":")[1])]
            return await self.menu_helper.edit_tag_values(
                self.chat, self.cmd, self.video, self.send_helper, self.destination, tag_name
            )


class EditTagValuesMenu(Menu):
    complete_callback = b"done"
    next_callback = b"next"
    prev_callback = b"prev"
    tag_callback = b"tag"
    page_height = 5
    page_width = 3

    def __init__(
            self,
            menu_helper: MenuHelper,
            chat: Chat,
            cmd: Message,
            video: Message,
            send_helper: GifSendHelper,
            destination: Channel,
            tag_manager: TagManager,
            tag_name: str
    ):
        super().__init__(menu_helper, chat, cmd, video)
        self.send_helper = send_helper
        self.destination = destination
        self.tag_manager = tag_manager
        self.tag_name = tag_name
        self.known_tag_values = sorted(self.tag_manager.get_values_for_tag(tag_name, [destination, chat]))
        self.page_num = 0
        self.current_tags = self.video.tags(self.menu_helper.database)

    @property
    def paged_tag_values(self) -> List[List[str]]:
        len_values = len(self.known_tag_values)
        page_size = self.page_height * self.page_width
        return [self.known_tag_values[i: i + page_size] for i in range(0, len_values, page_size)]

    @property
    def text(self) -> str:
        if not self.known_tag_values:
            # TODO: Capture text and stuff
            return f"There are no known previous values for the tag \"{self.tag_name}\" going to that destination.\n" \
                   f"Please tag the video using `tag {self.tag_name} <value>`"
        return f"Select which tags this video should have for \"{self.tag_name}\":"

    @property
    def buttons(self) -> Optional[List[List[Button]]]:
        tag_buttons = self.tag_buttons()
        page_buttons = self.page_buttons()
        return tag_buttons + [page_buttons]

    def tag_buttons(self) -> List[List[Button]]:
        if not self.known_tag_values:
            return [[self.button_done()]]
        current_page = self.paged_tag_values[self.page_num]
        columns = len(current_page) // self.page_height
        return [
            [self.button_for_tag(tag_value, i) for tag_value in current_page[i:i+columns]]
            for i in range(0, len(current_page), columns)
        ]

    def page_buttons(self) -> List[Button]:
        buttons = []
        if self.page_num > 0:
            buttons.append(Button.inline("⬅️Prev", self.prev_callback))
        buttons.append(self.button_done())
        if self.page_num < len(self.paged_tag_values) - 1:
            buttons.append(Button.inline("➡️Next", self.next_callback))
        return buttons

    def button_done(self) -> Button:
        return Button.inline("🖊️️️Done", self.complete_callback)

    def button_for_tag(self, tag_value: str, i: int) -> Button:
        has_tag = tag_value in self.current_tags.tags[self.tag_name]
        title = tag_value
        if has_tag:
            title = f"✔️{title}"
        value_num = self.page_num * self.page_width * self.page_height + i
        return Button.inline(title, f"{self.tag_callback}:{value_num}")

    async def handle_callback_query(
            self,
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.complete_callback:
            missing_tags = self.send_helper.missing_tags_for_video(self.video, self.destination)
            if missing_tags:
                return await self.menu_helper.additional_tags_menu(
                    self.chat, self.cmd, self.video, self.send_helper, self.destination, missing_tags
                )
            return await self.menu_helper.confirmation_menu(
                self.chat, self.cmd, self.video, self.send_helper, self.destination
            )
        if callback_query == self.next_callback:
            self.page_num += 1
            return [await self.send()]
        if callback_query == self.prev_callback:
            self.page_num -= 1
            return [await self.send()]
        if callback_query.startswith(self.tag_callback):
            tag_value = self.known_tag_values[int(callback_query.split(b":")[1])]
            self.current_tags.toggle_tag_value(self.tag_name, tag_value)
            return [await self.send()]


class SendConfirmationMenu(Menu):
    clear_confirm_menu = b"clear_menu"
    send_callback = b"send"
    send_queue = b"queue"

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
            callback_query: bytes
    ) -> Optional[List[Message]]:
        if callback_query == self.clear_confirm_menu:
            await self.delete()
            return []
        if callback_query == self.send_callback:
            return await self.send_helper.send_video(
                self.chat, self.video, self.cmd, self.destination, self.owner_id
            )
        if callback_query == self.send_queue:
            return await self.send_helper.send_video(
                self.chat, self.video, self.cmd, self.destination.queue, self.owner_id
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
