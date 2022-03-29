import asyncio
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import sys

import tqdm

from gif_pipeline.pipeline import PipelineConfig


class TqdmLoggingHandler(logging.Handler):
    def __init__(self, level=logging.NOTSET):
        super().__init__(level)

    def emit(self, record):
        try:
            msg = self.format(record)
            tqdm.tqdm.write(msg)
            self.flush()
        except (KeyboardInterrupt, SystemExit):
            raise
        except:
            self.handleError(record)


def setup_logging() -> None:
    os.makedirs("logs", exist_ok=True)
    formatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")

    pipeline_logger = logging.getLogger("gif_pipeline")
    pipeline_logger.setLevel(logging.DEBUG)
    file_handler = TimedRotatingFileHandler("logs/pipeline.log", when="midnight")
    file_handler.setFormatter(formatter)
    pipeline_logger.addHandler(file_handler)
    
    debug_logger = logging.getLogger()
    debug_logger.setLevel(logging.DEBUG)
    debug_file_handler = TimedRotatingFileHandler("logs/debug.log", when="midnight")
    debug_file_handler.setFormatter(formatter)
    debug_logger.addHandler(debug_file_handler)

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    console_handler = TqdmLoggingHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


def setup_loop() -> None:
    if sys.platform == 'win32':
        loop = asyncio.ProactorEventLoop()
        asyncio.set_event_loop(loop)


if __name__ == "__main__":
    setup_loop()
    setup_logging()
    with open("config.json", "r") as c:
        CONF = json.load(c)
    pipeline_conf = PipelineConfig(CONF)
    pipeline = pipeline_conf.initialise_pipeline()
    pipeline.initialise_helpers()
    pipeline.watch_workshop()
