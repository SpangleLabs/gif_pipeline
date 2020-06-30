import sqlite3
from collections import defaultdict
from typing import List, Dict, Set

import dateutil.parser

from group import ChatData
from message import MessageData


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
        row["reply_to"],
        row["sender_id"],
        bool(row["is_scheduled"])
    )


class Database:
    DB_FILE = "pipeline.sqlite"

    def __init__(self) -> None:
        self.conn = sqlite3.connect(self.DB_FILE)
        self.conn.row_factory = sqlite3.Row
        self._create_db()

    def _create_db(self) -> None:
        cur = self.conn.cursor()
        with open("database_schema.sql", "r") as f:
            cur.executescript(f.read())
        self.conn.commit()

    def save_chat(self, chat_data: ChatData):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO chats (chat_id, username, title) VALUES(?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username, title=excluded.title;",
            (chat_data.chat_id, chat_data.username, chat_data.title)
        )
        self.conn.commit()
        cur.close()

    def list_messages_for_chat(self, chat_data: ChatData) -> List[MessageData]:
        cur = self.conn.cursor()
        messages = []
        for row in cur.execute(
                "SELECT chat_id, message_id, datetime, text, is_forward, "
                "file_path, file_mime_type, reply_to, sender_id, is_scheduled "
                "FROM messages WHERE chat_id = ?",
                (chat_data.chat_id,)
        ):
            messages.append(message_data_from_row(row))
        return messages

    def save_message(self, message: MessageData) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO messages (chat_id, message_id, datetime, text, is_forward, "
            "file_path, file_mime_type, reply_to, sender_id, is_scheduled) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(chat_id, message_id, is_scheduled) "
            "DO UPDATE SET datetime=excluded.datetime, text=excluded.text, is_forward=excluded.is_forward, "
            "file_path=excluded.file_path, file_mime_type=excluded.file_mime_type, "
            "reply_to=excluded.reply_to, sender_id=excluded.sender_id",
            (
                message.chat_id, message.message_id, message.datetime, message.text, message.is_forward,
                message.file_path, message.file_mime_type, message.reply_to, message.sender_id, message.is_scheduled
            )
        )
        self.conn.commit()

    def remove_message(self, message: MessageData) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "DELETE FROM messages WHERE chat_id = ? AND message_id = ? AND is_scheduled = ?",
            (message.chat_id, message.message_id, message.is_scheduled)
        )
        self.conn.commit()

    def load_hashes(self) -> Dict[str, Set[MessageData]]:
        cur = self.conn.cursor()
        hashes: Dict[str, Set[MessageData]] = defaultdict(lambda: set())
        for row in cur.execute(
                "SELECT video_hashes.hash, m.chat_id, m.message_id, m.datetime, m.text, m.is_forward, "
                "m.file_path, m.file_mime_type, m.reply_to, m.sender_id, m.is_scheduled "
                "FROM video_hashes "
                "FULL OUTER JOIN messages m on video_hashes.entry_id = m.entry_id"
        ):
            if row["hash"] is None:
                continue
            hashes[row["hash"]].add(message_data_from_row(row))
        return hashes

    def get_hashes_for_message(self, message: MessageData) -> List[str]:
        cur = self.conn.cursor()
        hashes = []
        for row in cur.execute(
                "SELECT v.hash FROM video_hashes v "
                "RIGHT JOIN messages m on v.entry_id = m.entry_id W"
                "HERE m.chat_id = ? AND m.message_id = ? AND m.is_scheduled = ?",
                (message.chat_id, message.message_id, message.is_scheduled)
        ):
            hashes.append(row["hash"])
        return hashes

    def get_messages_for_hashes(self, image_hashes: List[str]) -> List[MessageData]:
        cur = self.conn.cursor()
        messages = []
        for row in cur.execute(
                "SELECT DISTINCT m.chat_id, m.message_id, m.datetime, m.text, m.is_forward, "
                "m.file_path, m.file_mime_type, m.reply_to, m.sender_id, m.is_scheduled "
                "FROM video_hashes v "
                "LEFT JOIN messages m on v.entry_id = m.entry_id "
                f"WHERE v.hash = {','.join('?' * len(image_hashes))}",
                image_hashes
        ):
            messages.append(message_data_from_row(row))
        return messages

    def save_hashes(self, message: MessageData, hashes: List[str]) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT entry_id FROM messages WHERE chat_id = ? AND message_id = ? AND is_scheduled = ?",
            (message.chat_id, message.message_id, message.is_scheduled)
        )
        result = cur.fetchone()
        if result is None:
            return
        entry_id = result["entry_id"]
        cur = self.conn.cursor()
        for hash_str in hashes:
            cur.execute(
                "INSERT INTO video_hashes (hash, entry_id) VALUES (?, ?) ON CONFLICT(hash, entry_id) DO NOTHING;",
                (hash_str, entry_id)
            )
        self.conn.commit()

    def remove_message_hashes(self, message: MessageData) -> None:
        cur = self.conn.cursor()
        cur.execute(
            "SELECT entry_id FROM messages WHERE chat_id = ? AND message_id = ? AND is_scheduled = ?",
            (message.chat_id, message.message_id, message.is_scheduled)
        )
        result = cur.fetchone()
        if result is None:
            return
        entry_id = result["entry_id"]
        cur = self.conn.cursor()
        cur.execute("DELETE FROM video_hashes WHERE entry_id = ?", (entry_id,))
        self.conn.commit()

    def get_message_history(self, message: MessageData) -> List[MessageData]:
        pass

    def get_message_family(self, message: MessageData) -> List[MessageData]:
        pass
