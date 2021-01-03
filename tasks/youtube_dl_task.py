import glob

import youtube_dl

from tasks.task import Task


class YoutubeDLTask(Task[str]):

    def __init__(self, link: str, output_path: str):
        self.link = link
        self.output_path = output_path

    async def run(self) -> str:
        ydl_opts = {"outtmpl": f"{self.output_path}%(ext)s"}
        # If downloading from reddit, use the DASH video, not the HLS video, which has corruption at 6 second intervals
        if "v.redd.it" in self.link or "reddit.com" in self.link:
            ydl_opts["format"] = "dash-VIDEO-1+dash-AUDIO-1/bestvideo+bestaudio/best"
        with youtube_dl.YoutubeDL(ydl_opts) as ydl:
            ydl.download([self.link])
        files = glob.glob(f"{self.output_path}*")
        return files[0]
