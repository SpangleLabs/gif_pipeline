import json
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional

from gif_pipeline.database import Database, MenuData

if TYPE_CHECKING:
    from gif_pipeline.helpers.menus.menu import Menu
    from gif_pipeline.message import Message


class MenuCache:
    def __init__(self, database: "Database"):
        self._menu_cache: Dict[int, Dict[int, SentMenu]] = defaultdict(lambda: {})
        self.database = database

    def add_menu(self, sent_menu: "SentMenu") -> None:
        self._menu_cache[sent_menu.menu.video.chat_data.chat_id][
            sent_menu.menu.video.message_data.message_id
        ] = sent_menu
        self.database.save_menu(sent_menu.to_data())

    def get_menu_by_video(self, video: "Message") -> Optional["SentMenu"]:
        return self._menu_cache.get(video.chat_data.chat_id, {}).get(video.message_data.message_id)

    def remove_menu_by_video(self, video: "Message") -> None:
        menu = self.get_menu_by_video(video)
        self.remove_sent_menu(menu)

    def remove_sent_menu(self, menu: Optional["SentMenu"]) -> None:
        if menu:
            del self._menu_cache[menu.menu.video.chat_data.chat_id][menu.menu.video.message_data.message_id]
            self.database.remove_menu(menu.to_data())

    def remove_menu_by_message(self, menu_msg: "Message") -> None:
        menu = self.get_menu_by_message_id(menu_msg.chat_data.chat_id, menu_msg.message_data.message_id)
        self.remove_sent_menu(menu)

    def get_menu_by_message_id(self, chat_id: int, menu_msg_id: int) -> Optional["SentMenu"]:
        menus = [
            menu
            for video_id, menu in self._menu_cache.get(chat_id, {}).items()
            if menu.msg.message_data.message_id == menu_msg_id
        ]
        return next(iter(menus), None)

    def list_entries(self) -> List["MenuEntry"]:
        return [
            MenuEntry(chat_id, video_msg_id, sent_menu)
            for chat_id, chat_cache in self._menu_cache.items()
            for video_msg_id, sent_menu in chat_cache.items()
        ]


@dataclass
class SentMenu:
    menu: "Menu"
    msg: "Message"
    clicked: bool = False

    def to_data(self) -> MenuData:
        return MenuData(
            self.menu.video.chat_data.chat_id,
            self.menu.video.message_data.message_id,
            self.msg.message_data.message_id,
            self.menu.json_name(),
            json.dumps(self.menu.to_json()),
            self.clicked,
        )


@dataclass
class MenuEntry:
    chat_id: int
    video_msg_id: int
    sent_menu: SentMenu
