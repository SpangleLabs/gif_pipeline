from typing import List, Optional

import sqlite3

from telethon import hints

from group import Channel, WorkshopGroup


class Database:
    DB_FILE = "pipeline.sqlite"

    def __init__(self):
        self.conn = sqlite3.connect(self.DB_FILE)
        self._create_db()

    def _create_db(self):
        cur = self.conn.cursor()
        with open("database_schema.sql", "r") as f:
            cur.executescript(f.read())
        self.conn.commit()

    def upsert_chat(self, chat_id: int, handle: Optional[str], title: str):
        cur = self.conn.cursor()
        cur.execute(
            "INSERT INTO chats (chat_id, username, title) VALUES(?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET username=excluded.username, title=excluded.title;",
            (chat_id, handle, title)
        )
        self.conn.commit()
        cur.close()

    def list_messages_for_chat(self, chat_id: int):
        pass

    def get_message_history(self, message_id):
        pass

    def get_message_family(self, message_id):
        pass

    def save_message(self, message):
        pass

    def get_messages_matching_hashes(self, hashes):
        pass
