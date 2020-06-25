from typing import List

import sqlite3

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
        pass

    def list_channels(self) -> List[Channel]:
        cur = self.conn.cursor()
        cur.execute("SELECT chat_handle, queue FROM channels")
        rows = cur.fetchall()
        channels = []
        for row in rows:
            channels.append(Channel(row[0], row[1]))
        cur.close()
        return channels

    def list_workshops(self) -> List[WorkshopGroup]:
        cur = self.conn.cursor()
        cur.execute("SELECT chat_id FROM workshops")
        rows = cur.fetchall()
        workshops = []
        for row in rows:
            workshops.append(WorkshopGroup(row[0]))
        cur.close()
        return workshops

    def get_message_history(self, message_id):
        pass

    def get_message_family(self, message_id):
        pass

    def save_message(self, message):
        pass

    def get_messages_matching_hashes(self, hashes):
        pass
