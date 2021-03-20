import json
from typing import Optional, Dict, List

from gif_pipeline.chat_data import ChatData
from gif_pipeline.database import Database
from gif_pipeline.message import MessageData, Message


def load_json_data() -> Dict[str, Dict[str, List[str]]]:
    deergifs_json = "deergifs_output.json"

    with open(deergifs_json, "r") as f:
        return json.load(f)


def get_chat_data_for_handle(database: Database, handle: str) -> Optional[ChatData]:
    channels = database.list_channels()
    for channel in channels:
        if channel.matches_handle(handle):
            return channel
    return None


database = Database()
chat_data = get_chat_data_for_handle(database, "deergifs")
tag_data = load_json_data()

for msg_key, json_tags in tag_data.items():
    try:
        msg_id = int(msg_key.split(".")[0])
    except ValueError:
        print(f"Skipping msg_key: {msg_key}, not an int")
        continue
    msg_data = MessageData(
        chat_data.chat_id,
        msg_id,
        None, None, None, None, None, None, None, None, None, False
    )
    msg = Message(msg_data, chat_data)
    entry_id = database.get_entry_id_for_message(msg_data)
    if entry_id is None:
        print(f"Skipping {msg_key}, not a valid channel post: {msg.telegram_link}")
        continue
    tags = msg.tags(database)
    tags.remove_all_values_for_tag("source_roughly")
    for tag_key, tag_values in json_tags.items():
        if tag_key.startswith("_"):
            continue
        if tag_key == "source_roughly":
            tag_key = "source"
        for tag_value in tag_values:
            tags.add_tag_value(tag_key, tag_value)
    database.save_tags(msg_data, tags)
    print(f"Saved tags for {msg_key}")
