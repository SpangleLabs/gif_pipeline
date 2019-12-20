import telethon.sync


class TelegramClient:
    def __init__(self, api_id, api_hash):
        self.client = telethon.sync.TelegramClient('duplicate_checker', api_id, api_hash)
        self.client.start()
        self.message_cache = {}

    def _save_message(self, message):
        chat_id = message.chat_id
        message_id = message.id
        if chat_id not in self.message_cache:
            self.message_cache[chat_id] = {}
        self.message_cache[chat_id][message_id] = message

    def _get_message(self, chat_id: int, message_id: int):
        if chat_id not in self.message_cache:
            return None
        return self.message_cache[chat_id].get(message_id)

    def iter_channel_messages(self, channel_handle: str):
        channel_entity = self.client.get_entity(channel_handle)
        for message in self.client.iter_messages(channel_entity):
            self._save_message(message)
            yield message

    def download_media(self, chat_id: int, message_id: int, path: str):
        message = self._get_message(chat_id, message_id)
        return self.client.download_media(message=message, file=path)
