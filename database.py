import sqlite3
from typing import List, Optional, Type, TypeVar, Set

import dateutil.parser

from group import ChatData, WorkshopData, ChannelData
from message import MessageData

chat_types = {
    "channel": ChannelData,
    "workshop": WorkshopData
}
chat_types_inv = {v: k for k, v in chat_types.items()}
T = TypeVar("T", bound=ChatData)


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
        chat_type = chat_types_inv[chat_data.__class__]
        cur.execute(
            "INSERT INTO chats (chat_id, username, title, chat_type) VALUES(?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username, title=excluded.title;",
            (chat_data.chat_id, chat_data.username, chat_data.title, chat_type)
        )
        self.conn.commit()
        cur.close()

    def list_chats(self, chat_type: Type[T]) -> List[T]:
        cur = self.conn.cursor()
        chats = []
        for row in cur.execute(
                "SELECT chat_id, username, title FROM chats WHERE chat_type = ?",
                (chat_types_inv[chat_type],)
        ):
            chats.append(chat_type(
                row["chat_id"],
                row["username"],
                row["title"]
            ))
        return chats

    def list_channels(self) -> List[ChannelData]:
        return self.list_chats(ChannelData)

    def list_workshops(self) -> List[WorkshopData]:
        return self.list_chats(WorkshopData)

    def get_chat_by_id(self, chat_id: int) -> Optional[ChatData]:
        cur = self.conn.cursor()
        cur.execute("SELECT chat_id, username, title, chat_type FROM chats WHERE chat_id = ?", (chat_id,))
        chat_row = cur.fetchone()
        if chat_row is None:
            return None
        chat_data_class = chat_types[chat_row["chat_type"]]
        return chat_data_class(
            chat_row["chat_id"],
            chat_row["username"],
            chat_row["title"]
        )

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

    def get_hashes_for_message(self, message: MessageData) -> List[str]:
        cur = self.conn.cursor()
        hashes = []
        for row in cur.execute(
                "SELECT vh.hash FROM messages m "
                "LEFT JOIN video_hashes vh on m.entry_id = vh.entry_id "
                "WHERE m.chat_id = ? AND m.message_id = ? AND m.is_scheduled = ?",
                (message.chat_id, message.message_id, message.is_scheduled)
        ):
            if row["hash"] is not None:
                hashes.append(row["hash"])
        return hashes

    def get_messages_needing_hashing(self) -> List[MessageData]:
        cur = self.conn.cursor()
        messages = []
        for row in cur.execute(
                "SELECT m.chat_id, m.message_id, m.datetime, m.text, m.is_forward, "
                "m.file_path, m.file_mime_type, m.reply_to, m.sender_id, m.is_scheduled "
                "FROM messages m "
                "LEFT JOIN video_hashes vh ON m.entry_id = vh.entry_id "
                "WHERE vh.hash IS NULL AND m.file_path IS NOT NULL"
        ):
            messages.append(message_data_from_row(row))
        return messages

    def get_messages_for_hashes(self, image_hashes: Set[str]) -> List[MessageData]:
        cur = self.conn.cursor()
        messages = []
        # TODO: can fail if there are too many hashes
        for row in cur.execute(
                "SELECT DISTINCT m.chat_id, m.message_id, m.datetime, m.text, m.is_forward, "
                "m.file_path, m.file_mime_type, m.reply_to, m.sender_id, m.is_scheduled "
                "FROM video_hashes v "
                "LEFT JOIN messages m on v.entry_id = m.entry_id "
                f"WHERE v.hash IN ({','.join('?' * len(image_hashes))}) AND m.datetime IS NOT NULL",
                list(image_hashes)
        ):
            messages.append(message_data_from_row(row))
        return messages

    def save_hashes(self, message: MessageData, hashes: Set[str]) -> None:
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
        """
        Returns a list of messages, from the specified message, up to the root message, via replies.
        :param message: the message to start climbing from
        :return: A list of messages from the specified to the root, ordered in reverse date order
        """
        cur = self.conn.cursor()
        messages = []
        for row in cur.execute(
                "WITH RECURSIVE parent(x) AS ("
                "  SELECT :msg_id "
                "    UNION ALL "
                "  SELECT m.reply_to "
                "  FROM messages m, parent "
                "  WHERE m.message_id=parent.x AND m.reply_to IS NOT NULL "
                "    AND m.chat_id = :chat_id AND m.is_scheduled = :scheduled"
                ") "
                "SELECT m.chat_id, m.message_id, m.datetime, m.text, m.is_forward, "
                "  m.file_path, m.file_mime_type, m.reply_to, m.sender_id, m.is_scheduled "
                "FROM parent p "
                "LEFT JOIN messages m ON m.message_id = p.x "
                "WHERE m.chat_id = :chat_id AND m.is_scheduled = :scheduled "
                "ORDER BY datetime DESC;",
                {
                    "msg_id": message.message_id,
                    "chat_id": message.chat_id,
                    "scheduled": message.is_scheduled
                }
        ):
            messages.append(message_data_from_row(row))
        return messages

    def get_message_family(self, message: MessageData) -> List[MessageData]:
        """
        List of messages in the specified message's family. I.e. messages which are replies to this one, and
        replies to those ones, etc
        :param message: The message to start descending the tree from
        :return: A list of messages, in ascending datetime order
        """
        cur = self.conn.cursor()
        messages = []
        for row in cur.execute(
                "WITH RECURSIVE children(x) AS ("
                "  SELECT :msg_id "
                "    UNION ALL "
                "  SELECT m.message_id "
                "  FROM messages m, children "
                "  WHERE m.reply_to = children.x AND m.chat_id = :chat_id AND m.is_scheduled = :scheduled"
                ") "
                "SELECT m.chat_id, m.message_id, m.datetime, m.text, m.is_forward,"
                "  m.file_path, m.file_mime_type, m.reply_to, m.sender_id, m.is_scheduled "
                "FROM children c "
                "LEFT JOIN messages m ON m.message_id = c.x "
                "WHERE m.chat_id = :chat_id AND m.is_scheduled = :scheduled "
                "ORDER BY m.datetime;",
                {
                    "msg_id": message.message_id,
                    "chat_id": message.chat_id,
                    "scheduled": message.is_scheduled
                }
        ):
            messages.append(message_data_from_row(row))
        return messages
