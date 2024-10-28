import glob
from typing import Optional

from gif_pipeline.tasks.task import Task, run_subprocess

yt_dl_pkg = "yt-dlp"


class YoutubeDLTask(Task[str]):

    def __init__(self, link: str, output_path: str, description: str = None) -> None:
        super().__init__(description=description)
        self.link = link
        self.output_path = output_path

    async def run(self) -> str:
        args = [yt_dl_pkg, "--output", f"{self.output_path}%(playlist_index|00)s.%(ext)s", self.link]
        await run_subprocess(args)
        files = glob.glob(f"{self.output_path}*")
        return files[0]

    def _formatted_args(self) -> list[str]:
        return self._format_args({
            "link": self.link,
            "output_path": self.output_path,
        })


class YoutubeDLDumpJsonTask(Task[str]):

    def __init__(
            self,
            link: str,
            end: Optional[int] = None,
            start: Optional[int] = None,
            description: str = None,
    ) -> None:
        super().__init__(description=description)
        self.link = link
        self.end = end
        self.start = start

    async def run(self) -> str:
        args = [yt_dl_pkg, "--dump-json"]
        if self.start:
            args += ["--playlist-start", f"{self.start}"]
        if self.end:
            args += [f"--playlist-end", f"{self.end}"]
        args.append(self.link)
        resp = await run_subprocess(args)
        return resp

    def _formatted_args(self) -> list[str]:
        return self._format_args({"link": self.link}) + self._format_non_null_args({
            "start": self.start,
            "end": self.end,
        })