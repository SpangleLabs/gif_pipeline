import glob

from gif_pipeline.tasks.task import Task, run_subprocess

yt_dl_pkg = "yt-dlp"


class YoutubeDLTask(Task[str]):

    def __init__(self, link: str, output_path: str):
        self.link = link
        self.output_path = output_path

    async def run(self) -> str:
        args = [yt_dl_pkg, "--output", f"{self.output_path}%(ext)s", self.link]
        await run_subprocess(args)
        files = glob.glob(f"{self.output_path}*")
        return files[0]
