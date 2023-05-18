import json
from typing import List

from gif_pipeline.chat_config import WorkshopConfig
from gif_pipeline.chat_data import ChatData
from gif_pipeline.message import MessageData
from gif_pipeline.telegram_client import TelegramClient


async def scan_messages(client: TelegramClient, chat: ChatData) -> List[MessageData]:
    error_messages = []
    all_messages = 0
    async for msg in client.iter_channel_messages(chat):
        all_messages += 1
        if msg.text is not None and msg.text.startswith("Subscription to") and "failed due to: " in msg.text:
            error_messages.append(msg)
            if len(error_messages) % 10 == 0:
                print(f"Found some error messages, {len(error_messages)} so far")
        if all_messages % 100 == 0:
            print(f"Checked {all_messages} messages")
    print(f"In total there are {all_messages} messages and {len(error_messages)} subscription errors")
    return error_messages


# CHAT_HANDLE = 1444399966  # gif pipeline (3046 deleted)
# CHAT_HANDLE = 1399568574  # tiger gifs input (5953 deleted)
# CHAT_HANDLE = 1741989099  # chicken gifs input (55 deleted)
# CHAT_HANDLE = 1702783924  # alpaca gifs input (5880 deleted)
# CHAT_HANDLE = 1770412579  # corvid gifs input (3054 deleted)
# CHAT_HANDLE = 1587179114  # goat gifs input (41 deleted)
# CHAT_HANDLE = 1564515446  # pig gifs input (5 deleted)
# CHAT_HANDLE = 1768819453  # horse gifs input (9125 deleted)
# CHAT_HANDLE = 1702491484  # cow gifs input (8141 deleted)
# CHAT_HANDLE = 1679650870  # other animals gifs input (17819 deleted)
# CHAT_HANDLE = 1625461861  # deer gifs input (5883 deleted)
# CHAT_HANDLE = 1632505756  # sheep gifs input (2185 deleted)
# CHAT_HANDLE = 1671037190  # elephant gifs input (43 deleted)
# CHAT_HANDLE = 1682124643  # fox gifs input (14164 deleted)
# CHAT_HANDLE = 1471640955  # mammal gifs input (0 deleted)


if __name__ == "__main__":
    with open("config.json", "r") as f:
        config = json.load(f)

    c = TelegramClient(config["api_id"], config["api_hash"])
    c.synchronise_async(c.initialise())
    chat_conf = WorkshopConfig(CHAT_HANDLE)
    chat_data = c.synchronise_async(c.get_workshop_data(chat_conf.handle))

    error_msgs = c.synchronise_async(scan_messages(c, chat_data))
    print("---")
    if input("Would you like to preview the messages? [y/N]").lower() == "y":
        for msg in error_msgs:
            print(msg.text.split("\n")[0][:300])
        print("---")
    print(f"There are {len(error_msgs)} errors, would you like to delete them?")
    if input("Delete messages? [y/N] ").lower() == "y":
        c.synchronise_async(c.delete_messages(error_msgs))
        print("Deleted!")
