import telethon


class TelegramClient:
    def __init__(self, api_id, api_hash):
        self.client = telethon.TelegramClient('duplicate_checker', api_id, api_hash)
        self.client.start()

    async def iter_channel_messages(self, channel_handle: str):
        channel_entity = await self.client.get_entity(channel_handle)
        return self.client.iter_messages(channel_entity)

    async def download_media(self, message, path):
        return self.client.download_media(message=message, file=path)
