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

    def get_message_history(self, message_id):
        pass

    def get_message_family(self, message_id):
        pass

    def save_message(self, message):
        pass

    def get_messages_matching_hashes(self, hashes):
        pass
