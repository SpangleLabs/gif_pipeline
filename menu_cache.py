from collections import defaultdict
from dataclasses import dataclass
from typing import Optional, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from helpers.menu_helper import Menu
    from message import Message


class MenuCache:
    def __init__(self):
        # TODO: save and load menu cache, so that menus can resume when bot reboots
        self._menu_cache: Dict[int, Dict[int, SentMenu]] = defaultdict(lambda: {})

    def add_menu(self, sent_menu: 'SentMenu') -> None:
        self._menu_cache[
            sent_menu.menu.video.chat_data.chat_id
        ][
            sent_menu.menu.video.message_data.message_id
        ] = sent_menu

    def get_menu_by_video(self, video: Message) -> Optional['SentMenu']:
        return self._menu_cache.get(video.chat_data.chat_id, {}).get(video.message_data.message_id)

    def remove_menu_by_video(self, video: Message) -> None:
        menu = self.get_menu_by_video(video)
        if menu:
            del self._menu_cache[video.chat_data.chat_id][video.message_data.message_id]

    def get_menu_by_message_id(self, chat_id: int, menu_msg_id: int) -> Optional['SentMenu']:
        menus = [
            menu for video_id, menu in self._menu_cache.get(chat_id, {}).items()
            if menu.msg.message_data.message_id == menu_msg_id
        ]
        return next(iter(menus), None)


@dataclass
class SentMenu:
    menu: 'Menu'
    msg: Message
    clicked: bool = False
