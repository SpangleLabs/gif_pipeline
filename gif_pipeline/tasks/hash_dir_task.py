import asyncio
import glob
from concurrent.futures import Executor

import imagehash
from PIL import Image

from gif_pipeline.tasks.task import Task


def hash_image(image_file: str) -> str:
    image = Image.open(image_file)
    image_hash = str(imagehash.dhash(image))
    return image_hash


class HashDirectoryTask(Task[set[str]]):

    def __init__(self, directory: str, executor: Executor) -> None:
        self.directory = directory
        self.executor = executor

    async def run(self) -> set[str]:
        image_files = glob.glob(f"{self.directory}/*.png")
        loop = asyncio.get_running_loop()
        hash_list = await asyncio.gather(
            *[loop.run_in_executor(self.executor, hash_image, image_file) for image_file in image_files]
        )
        return set(hash_list)
