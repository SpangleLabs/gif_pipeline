import logging
from typing import Optional, List
from qreader import QReader
import cv2


from gif_pipeline.chat import Chat
from gif_pipeline.database import Database
from gif_pipeline.helpers.helpers import Helper, find_video_for_message
from gif_pipeline.message import Message
from gif_pipeline.tasks.task_worker import TaskWorker
from gif_pipeline.telegram_client import TelegramClient

logger = logging.getLogger(__name__)


class QRCodeReaderHelper(Helper):

    def __init__(self, database: "Database", client: "TelegramClient", worker: TaskWorker) -> None:
        super().__init__(database, client, worker)
        self.qreader = QReader()

    async def on_new_message(self, chat: Chat, message: Message) -> Optional[List[Message]]:
        text_clean = message.message_data.text.lower().strip().replace(" ", "")
        if text_clean not in ["qr", "qrcode", "readqr", "readqrcode"]:
            return
        video = find_video_for_message(chat, message)
        if video is None:
            return [await self.send_text_reply(
                chat,
                message,
                "I am not sure which image you would like to scan for QR codes. "
                "Please reply to the message with the image."
            )]
        # Parse image
        try:
            image = cv2.cvtColor(cv2.imread(video.message_data.file_path), cv2.COLOR_BGR2RGB)
        except Exception as e:
            logger.warning("QRCodeReaderHelper failed to read image.", exc_info=e)
            return [await self.send_text_reply(chat, message, "Failed to open image for QR code parsing.")]
        # Detect and decode QR codes
        try:
            decoded_text = self.qreader.detect_and_decode(image=image)
        except Exception as e:
            logger.warning("Failed to detect and decode QR codes in image.", exc_info=e)
            return [await self.send_text_reply(chat, message, "Failed to detect and decode QR codes in image.")]
        # Send reply
        qr_count = len(decoded_text)
        resp = f"There were {qr_count} QR codes detected in that image.\n"
        for qr_code in decoded_text:
            if qr_code is None:
                resp += "- Could not decode this QR code."
            else:
                resp += f"- {qr_code}\n"
        return [await self.send_text_reply(chat, message, resp)]



