import datetime
import logging
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from sqlite3 import Cursor
from threading import RLock
from typing import List, Optional, Type, TypeVar, Set, Iterable, Dict, Tuple, Union, ContextManager

import dateutil.parser

from gif_pipeline.chat_data import ChatData, ChannelData, WorkshopData
from gif_pipeline.message import MessageData
from gif_pipeline.video_tags import TagEntry, VideoTags

chat_types = {
    "channel": ChannelData,
    "workshop": WorkshopData
}
chat_types_inv = {v: k for k, v in chat_types.items()}
T = TypeVar("T", bound=ChatData)

logger = logging.getLogger(__name__)


def message_data_from_row(row: sqlite3.Row) -> MessageData:
    return MessageData(
        row["chat_id"],
        row["message_id"],
        dateutil.parser.parse(row["datetime"]),
        row["text"],
        bool(row["is_forward"]),
        row["file_path"] is not None,
        row["file_path"],
        row["file_mime_type"],
        row["file_size"],
        row["reply_to"],
        row["sender_id"],
        bool(row["is_scheduled"]),
        row["forwarded_channel_link"]
    )


def parse_bool(db_bool: Optional[int]) -> Optional[int]:
    if db_bool is None:
        return None
    return bool(db_bool)


@dataclass
class MenuData:
    chat_id: int
    video_msg_id: int
    menu_msg_id: int
    menu_type: str
    menu_json_str: str
    clicked: bool


@dataclass
class SubscriptionData:
    subscription_id: int
    feed_link: str
    chat_id: int
    last_check_time: Optional[str]
    check_rate: Optional[str]
    enabled: Optional[bool]
    failures: int


class Database:
    DB_FILE = "pipeline.sqlite"

    def __init__(self, *, filename: str = DB_FILE) -> None:
        self.conn = sqlite3.connect(filename, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = RLock()
        self._create_db()

    def _create_db(self) -> None:
        cur = self.conn.cursor()
        directory = Path(__file__).parent
        with open(directory / "database_schema.sql", "r") as f:
            cur.executescript(f.read())
        self.conn.commit()

    @contextmanager
    def _execute(self, query: str, args: Optional[Union[Tuple, Dict]] = None) -> ContextManager[Cursor]:
        with self._lock:
            cur = self.conn.cursor()
            try:
                if args:
                    result = cur.execute(query, args)
                else:
                    result = cur.execute(query)
                self.conn.commit()
                yield result
            finally:
                cur.close()

    def _just_execute(self, query: str, args: Optional[Union[Tuple, Dict]] = None) -> None:
        with self._execute(query, args):
            pass

    def save_chat(self, chat_data: ChatData):
        chat_type = chat_types_inv[chat_data.__class__]
        self._just_execute(
            "INSERT INTO chats (chat_id, access_hash, username, title, chat_type, broadcast, megagroup) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id) "
            "DO UPDATE SET access_hash=excluded.access_hash, username=excluded.username, title=excluded.title, "
            "broadcast=excluded.broadcast, megagroup=excluded.megagroup;",
            (
                chat_data.chat_id, chat_data.access_hash, chat_data.username, chat_data.title, chat_type,
                chat_data.broadcast, chat_data.megagroup
            )
        )

    def remove_chat(self, chat_data: ChatData):
        messages = self.list_messages_for_chat(chat_data)
        for message in messages:
            self.remove_message(message)
        self._just_execute(
            "DELETE FROM chats WHERE chat_id = ?",
            (chat_data.chat_id, )
        )

    def list_chats(self, chat_type: Type[T]) -> List[T]:
        chats = []
        with self._execute(
            "SELECT chat_id, access_hash, username, title, broadcast, megagroup FROM chats WHERE chat_type = ?",
            (chat_types_inv[chat_type],)
        ) as result:
            for row in result:
                chats.append(chat_type(
                    row["chat_id"],
                    row["access_hash"],
                    row["username"],
                    row["title"],
                    parse_bool(row["broadcast"]),
                    parse_bool(row["megagroup"])
                ))
        return chats

    def list_channels(self) -> List[ChannelData]:
        return self.list_chats(ChannelData)

    def list_workshops(self) -> List[WorkshopData]:
        return self.list_chats(WorkshopData)

    def get_chat_by_id(self, chat_id: int) -> Optional[ChatData]:
        with self._execute(
                "SELECT chat_id, access_hash, username, title, chat_type, broadcast, megagroup "
                "FROM chats WHERE chat_id = ?",
                (chat_id,)
        ) as result:
            chat_row = next(result, None)
            if chat_row is None:
                return None
            chat_data_class = chat_types[chat_row["chat_type"]]
            return chat_data_class(
                chat_row["chat_id"],
                chat_row["access_hash"],
                chat_row["username"],
                chat_row["title"],
                parse_bool(chat_row["broadcast"]),
                parse_bool(chat_row["megagroup"])
            )

    def list_messages_for_chat(self, chat_data: ChatData) -> List[MessageData]:
        messages = []
        with self._execute(
                "SELECT chat_id, message_id, datetime, text, is_forward, "
                "file_path, file_mime_type, file_size, reply_to, sender_id, is_scheduled, forwarded_channel_link "
                "FROM messages WHERE chat_id = ?",
                (chat_data.chat_id,)
        ) as result:
            for row in result:
                messages.append(message_data_from_row(row))
        return messages

    def save_message(self, message: MessageData) -> None:
        self._just_execute(
            "INSERT INTO messages (chat_id, message_id, datetime, text, is_forward, "
            "file_path, file_mime_type, reply_to, sender_id, is_scheduled, forwarded_channel_link) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, message_id, is_scheduled) "
            "DO UPDATE SET datetime=excluded.datetime, text=excluded.text, is_forward=excluded.is_forward, "
            "file_path=excluded.file_path, file_mime_type=excluded.file_mime_type, "
            "reply_to=excluded.reply_to, sender_id=excluded.sender_id, "
            "forwarded_channel_link=excluded.forwarded_channel_link",
            (
                message.chat_id, message.message_id, message.datetime, message.text, message.is_forward,
                message.file_path, message.file_mime_type, message.reply_to, message.sender_id, message.is_scheduled,
                message.forwarded_channel_link
            )
        )

    def get_tags_for_message(self, message: MessageData) -> List[TagEntry]:
        entry_id = self.get_entry_id_for_message(message)
        entries = []
        with self._execute("SELECT tag_name, tag_value FROM video_tags WHERE entry_id = ?", (entry_id,)) as result:
            for row in result:
                entries.append(TagEntry(
                    row["tag_name"],
                    row["tag_value"]
                ))
        return entries

    def get_tags_for_chat(self, chat_data: ChatData, is_scheduled: bool = False) -> Dict[int, List[TagEntry]]:
        results = {}
        with self._execute(
            "SELECT msg.message_id, tags.tag_name, tags.tag_value "
            "FROM video_tags tags "
            "LEFT JOIN messages msg ON tags.entry_id = msg.entry_id "
            "WHERE msg.chat_id = ? AND is_scheduled = ?",
            (chat_data.chat_id, is_scheduled)
        ) as result:
            for row in result:
                msg_id = row["message_id"]
                if msg_id not in result:
                    results[msg_id] = []
                results[msg_id].append(TagEntry(
                    row["tag_name"],
                    row["tag_value"]
                ))
        return results

    def get_thumbnails_for_chat(self, chat_data: ChatData, is_scheduled: bool = False) -> Dict[int, bytes]:
        results = {}
        with self._execute(
            "SELECT msg.message_id, thumbs.thumbnail "
            "FROM video_thumbnails thumbs "
            "LEFT JOIN messages msg ON thumbs.entry_id = msg.entry_id "
            "WHERE msg.chat_id = ? AND is_scheduled = ?",
            (chat_data.chat_id, is_scheduled)
        ) as result:
            for row in result:
                msg_id = row["message_id"]
                thumb_data = row["thumbnail"]
                results[msg_id] = thumb_data
        return results

    def list_tag_values(self, tag_name: str, chat_ids: List[int]) -> List[str]:
        with self._execute(
            "SELECT vt.tag_value "
            "FROM video_tags vt "
            "LEFT JOIN messages m ON m.entry_id = vt.entry_id "
            f"WHERE vt.tag_name = ? AND m.chat_id IN ({','.join('?' * len(chat_ids))})",
            (tag_name, *chat_ids)
        ) as result:
            tag_values = [
                row["tag_value"]
                for row in result
            ]
            return tag_values

    def save_tags(self, message: MessageData, tags: VideoTags) -> None:
        entry_id = self.get_entry_id_for_message(message)
        # Delete tags
        self._remove_tags_by_entry_id(entry_id)
        # Add tags
        for tag in tags.to_entries():
            self._just_execute(
                "INSERT INTO video_tags (entry_id, tag_name, tag_value) "
                "VALUES (?, ?, ?)",
                (entry_id, tag.tag_name, tag.tag_value)
            )

    def save_tags_for_key(self, message: MessageData, tags: VideoTags, tag_name: str) -> None:
        entry_id = self.get_entry_id_for_message(message)
        # Delete values for tag
        self._just_execute("DELETE FROM video_tags WHERE entry_id = ? AND tag_name = ?", (entry_id, tag_name))
        # Add tags
        for tag in tags.to_entries_for_tag(tag_name):
            self._just_execute(
                "INSERT INTO video_tags (entry_id, tag_name, tag_value) "
                "VALUES (?, ?, ?)",
                (entry_id, tag.tag_name, tag.tag_value)
            )

    def remove_tags(self, message: MessageData) -> None:
        entry_id = self.get_entry_id_for_message(message)
        self._remove_tags_by_entry_id(entry_id)

    def _remove_tags_by_entry_id(self, entry_id: int) -> None:
        self._just_execute("DELETE FROM video_tags WHERE entry_id = ?", (entry_id,))

    def remove_message(self, message: MessageData) -> None:
        entry_id = self.get_entry_id_for_message(message)
        self._remove_message_hashes_by_entry_id(entry_id)
        self._remove_tags_by_entry_id(entry_id)
        self._remove_menu_by_entry_id(entry_id)
        self._just_execute(
            "DELETE FROM messages WHERE chat_id = ? AND message_id = ? AND is_scheduled = ?",
            (message.chat_id, message.message_id, message.is_scheduled)
        )

    def get_hashes_for_message(self, message: MessageData) -> List[str]:
        hashes = []
        with self._execute(
                "SELECT vh.hash FROM messages m "
                "LEFT JOIN video_hashes vh on m.entry_id = vh.entry_id "
                "WHERE m.chat_id = ? AND m.message_id = ? AND m.is_scheduled = ?",
                (message.chat_id, message.message_id, message.is_scheduled)
        ) as result:
            for row in result:
                if row["hash"] is not None:
                    hashes.append(row["hash"])
        return hashes

    def get_messages_needing_hashing(self) -> List[MessageData]:
        messages = []
        with self._execute(
                "SELECT m.chat_id, m.message_id, m.datetime, m.text, m.is_forward, "
                "m.file_path, m.file_mime_type, m.file_size, m.reply_to, m.sender_id, m.is_scheduled, "
                "m.forwarded_channel_link "
                "FROM messages m "
                "LEFT JOIN video_hashes vh ON m.entry_id = vh.entry_id "
                "WHERE vh.hash IS NULL AND m.file_path IS NOT NULL"
        ) as result:
            for row in result:
                messages.append(message_data_from_row(row))
        return messages

    def get_messages_for_hashes(self, image_hashes: Set[str]) -> List[MessageData]:
        messages = defaultdict(lambda: {})
        # Chunk this up, as it will otherwise fail if there are too many hashes
        image_hash_lists = chunks(image_hashes, 500)
        for image_hash_list in image_hash_lists:
            with self._execute(
                    "SELECT DISTINCT m.chat_id, m.message_id, m.datetime, m.text, m.is_forward, "
                    "m.file_path, m.file_mime_type, m.file_size, m.reply_to, m.sender_id, m.is_scheduled, "
                    "m.forwarded_channel_link "
                    "FROM video_hashes v "
                    "LEFT JOIN messages m on v.entry_id = m.entry_id "
                    f"WHERE v.hash IN ({','.join('?' * len(image_hash_list))}) AND m.datetime IS NOT NULL",
                    tuple(image_hash_list)
            ) as result:
                for row in result:
                    messages[row["chat_id"]][row["message_id"]] = message_data_from_row(row)
        return [msg for chat_id, chat_msgs in messages.items() for msg_id, msg in chat_msgs.items()]

    def get_entry_id_for_message(self, message: MessageData) -> Optional[int]:
        return self.get_entry_id_by_chat_and_message_id(message.chat_id, message.message_id, message.is_scheduled)

    def get_entry_id_by_chat_and_message_id(self, chat_id: int, message_id: int, is_scheduled: bool) -> Optional[int]:
        with self._execute(
            "SELECT entry_id FROM messages WHERE chat_id = ? AND message_id = ? AND is_scheduled = ?",
            (chat_id, message_id, is_scheduled)
        ) as result:
            row = next(result, None)
            if row is None:
                return
            return row["entry_id"]

    def save_hashes(self, message: MessageData, hashes: Set[str]) -> None:
        entry_id = self.get_entry_id_for_message(message)
        for hash_str in hashes:
            self._just_execute(
                "INSERT INTO video_hashes (hash, entry_id) VALUES (?, ?) ON CONFLICT(hash, entry_id) DO NOTHING;",
                (hash_str, entry_id)
            )

    def remove_message_hashes(self, message: MessageData) -> None:
        entry_id = self.get_entry_id_for_message(message)
        self._remove_message_hashes_by_entry_id(entry_id)

    def _remove_message_hashes_by_entry_id(self, entry_id: int) -> None:
        self._just_execute("DELETE FROM video_hashes WHERE entry_id = ?", (entry_id,))

    def get_message_history(self, message: MessageData) -> List[MessageData]:
        """
        Returns a list of messages, from the specified message, up to the root message, via replies.
        :param message: the message to start climbing from
        :return: A list of messages from the specified to the root, ordered in reverse date order
        """
        messages = []
        with self._execute(
                "WITH RECURSIVE parent(x) AS ("
                "  SELECT :msg_id "
                "    UNION ALL "
                "  SELECT m.reply_to "
                "  FROM messages m, parent "
                "  WHERE m.message_id=parent.x AND m.reply_to IS NOT NULL "
                "    AND m.chat_id = :chat_id AND m.is_scheduled = :scheduled"
                ") "
                "SELECT m.chat_id, m.message_id, m.datetime, m.text, m.is_forward, "
                "  m.file_path, m.file_mime_type, m.file_size, m.reply_to, m.sender_id, m.is_scheduled, "
                "  m.forwarded_channel_link "
                "FROM parent p "
                "LEFT JOIN messages m ON m.message_id = p.x "
                "WHERE m.chat_id = :chat_id AND m.is_scheduled = :scheduled "
                "ORDER BY datetime DESC;",
                {
                    "msg_id": message.message_id,
                    "chat_id": message.chat_id,
                    "scheduled": message.is_scheduled
                }
        ) as result:
            for row in result:
                messages.append(message_data_from_row(row))
        return messages

    def get_message_family(self, message: MessageData) -> List[MessageData]:
        """
        List of messages in the specified message's family. I.e. messages which are replies to this one, and
        replies to those ones, etc
        :param message: The message to start descending the tree from
        :return: A list of messages, in ascending datetime order
        """
        messages = []
        with self._execute(
                "WITH RECURSIVE children(x) AS ("
                "  SELECT :msg_id "
                "    UNION ALL "
                "  SELECT m.message_id "
                "  FROM messages m, children "
                "  WHERE m.reply_to = children.x AND m.chat_id = :chat_id AND m.is_scheduled = :scheduled"
                ") "
                "SELECT m.chat_id, m.message_id, m.datetime, m.text, m.is_forward,"
                "  m.file_path, m.file_mime_type, m.file_size, m.reply_to, m.sender_id, m.is_scheduled, "
                "  m.forwarded_channel_link "
                "FROM children c "
                "LEFT JOIN messages m ON m.message_id = c.x "
                "WHERE m.chat_id = :chat_id AND m.is_scheduled = :scheduled "
                "ORDER BY m.datetime;",
                {
                    "msg_id": message.message_id,
                    "chat_id": message.chat_id,
                    "scheduled": message.is_scheduled
                }
        ) as result:
            for row in result:
                messages.append(message_data_from_row(row))
        return messages

    def save_menu(self, menu_data: MenuData) -> None:
        menu_entry_id = self.get_entry_id_by_chat_and_message_id(menu_data.chat_id, menu_data.menu_msg_id, False)
        video_entry_id = self.get_entry_id_by_chat_and_message_id(menu_data.chat_id, menu_data.video_msg_id, False)
        self._just_execute(
            "INSERT INTO menu_cache (menu_entry_id, video_entry_id, menu_type, menu_json_str, clicked) "
            "VALUES (?, ?, ?, ?, ?)"
            "ON CONFLICT(menu_entry_id) "
            "DO UPDATE SET video_entry_id=excluded.video_entry_id, menu_type=excluded.menu_type, "
            "menu_json_str=excluded.menu_json_str, clicked=excluded.clicked",
            (menu_entry_id, video_entry_id, menu_data.menu_type, menu_data.menu_json_str, menu_data.clicked)
        )

    def list_menus(self) -> List[MenuData]:
        menu_data_entries = []
        with self._execute(
            "SELECT mm.chat_id, mm.message_id as menu_msg_id, vm.message_id as video_msg_id, "
            "mc.menu_type, mc.menu_json_str, mc.clicked "
            "FROM menu_cache mc "
            "LEFT JOIN messages mm ON mm.entry_id = mc.menu_entry_id "
            "LEFT JOIN messages vm ON vm.entry_id = mc.video_entry_id"
        ) as result:
            for row in result:
                menu_data_entries.append(
                    MenuData(
                        row["chat_id"],
                        row["video_msg_id"],
                        row["menu_msg_id"],
                        row["menu_type"],
                        row["menu_json_str"],
                        bool(row["clicked"])
                    )
                )
        return menu_data_entries

    def remove_menu(self, menu_data: MenuData) -> None:
        menu_entry_id = self.get_entry_id_by_chat_and_message_id(menu_data.chat_id, menu_data.menu_msg_id, False)
        self._remove_menu_by_entry_id(menu_entry_id)

    def _remove_menu_by_entry_id(self, menu_entry_id: int) -> None:
        self._just_execute("DELETE FROM menu_cache WHERE menu_entry_id = ?", (menu_entry_id,))

    def list_subscriptions(self) -> List[SubscriptionData]:
        sub_entries = []
        with self._execute(
            "SELECT subscription_id, feed_link, chat_id, last_check_time, check_rate, enabled, failures "
            "FROM subscriptions"
        ) as result:
            for row in result:
                sub_entries.append(
                    SubscriptionData(
                        row["subscription_id"],
                        row["feed_link"],
                        row["chat_id"],
                        row["last_check_time"],
                        row["check_rate"],
                        bool(row["enabled"]),
                        row["failures"]
                    )
                )
        return sub_entries

    def list_item_ids_for_subscription(self, subscription: SubscriptionData) -> List[str]:
        items = []
        with self._execute(
            "SELECT item_id FROM subscription_items WHERE subscription_id = ?",
                (subscription.subscription_id, )
        ) as result:
            for row in result:
                items.append(row["item_id"])
        return items

    def save_subscription(
            self,
            subscription: SubscriptionData,
            seen_item_ids: Optional[List[str]] = None
    ) -> SubscriptionData:
        seen_item_ids = seen_item_ids or []
        with self._execute(
            "INSERT INTO subscriptions (subscription_id, feed_link, chat_id, last_check_time, check_rate, enabled, "
            "failures)"
            " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (subscription_id)"
            " DO UPDATE SET feed_link=excluded.feed_link, chat_id=excluded.chat_id, "
            " last_check_time=excluded.last_check_time, check_rate=excluded.check_rate, enabled=excluded.enabled, "
            "failures=excluded.failures",
            (
                subscription.subscription_id, subscription.feed_link, subscription.chat_id,
                subscription.last_check_time, subscription.check_rate, subscription.enabled, subscription.failures
            )
        ) as result:
            if subscription.subscription_id is None:
                subscription.subscription_id = result.lastrowid
            for seen_item_id in seen_item_ids:
                self._just_execute(
                    "INSERT INTO subscription_items (subscription_id, item_id) VALUES (?, ?)"
                    " ON CONFLICT (subscription_id, item_id) DO NOTHING",
                    (subscription.subscription_id, seen_item_id)
                )
            with self._execute(
                "DELETE FROM subscription_items"
                " WHERE subscription_id = ?"
                f" AND item_id NOT IN ({','.join('?' * len(seen_item_ids))})",
                (subscription.subscription_id, *seen_item_ids)
            ) as cursor:
                logger.debug(
                    "Deleted %s subscription item rows for subscription ID: %s",
                    cursor.rowcount,
                    subscription.subscription_id,
                )
        return subscription

    def remove_subscription(self, sub: SubscriptionData) -> None:
        self._just_execute("DELETE FROM subscription_items WHERE subscription_id = ?", (sub.subscription_id,))
        self._just_execute("DELETE FROM subscriptions WHERE subscription_id = ?", (sub.subscription_id,))

    def save_thumbnail(self, message_data: MessageData, thumb_data: bytes, thumbnail_ts: float, generation_ts: datetime.datetime):
        entry_id = self.get_entry_id_for_message(message_data)
        self._just_execute(
            "INSERT INTO video_thumbnails (entry_id, thumbnail, thumbnail_timestamp, creation_time)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT (entry_id) DO UPDATE SET thumbnail=excluded.thumbnail,"
            " thumbnail_timestamp=excluded.thumbnail_timestamp, creation_time=excluded.creation_time",
            (entry_id, thumb_data, thumbnail_ts, generation_ts)
        )

    def get_thumbnail_data(self, message_data: MessageData) -> Optional[bytes]:
        entry_id = self.get_entry_id_for_message(message_data)
        with self._execute(
            "SELECT thumbnail FROM video_thumbnails WHERE entry_id = ?",
            (entry_id,)
        ) as result:
            row = next(result, None)
            if row is None:
                return
            return row["thumbnail"]


S = TypeVar('S')


def chunks(lst: Iterable[S], n: int) -> List[List[S]]:
    """Yield successive n-sized chunks from lst."""
    lst = list(lst)
    for i in range(0, len(lst), n):
        yield list(lst)[i:i + n]
