import re

from gif_pipeline.tasks.task import Task, TaskException, run_subprocess
from gif_pipeline.tasks.youtube_dl_task import yt_dl_pkg

yt_dl_github_repo = "https://github.com/yt-dlp/yt-dlp/"

class UpdateYoutubeDLTask(Task[str]):

    async def run(self) -> str:
        git_url = f"git+{yt_dl_github_repo.rstrip('/')}.git"
        args = ["pip", "install", git_url, "--force-reinstall"]
        stdout = await run_subprocess(args)
        lines = stdout.splitlines()
        last_line = lines[-1]
        if last_line.startswith("Successfully installed"):
            updates = last_line.split()
            yt_update = next(filter(lambda u: u.startswith(f"{yt_dl_pkg}-"), updates), None)
            if yt_update:
                return f"Updated {yt_dl_pkg} to {yt_update}"
            return "Updated other packages"
        up_to_date_regex = re.compile(
            f"^Requirement already (up-to-date|satisfied): {re.escape(yt_dl_pkg)} .* \\(([^)]+)\\)$",
            re.MULTILINE
        )
        yt_up_to_date = up_to_date_regex.search(stdout)
        if yt_up_to_date is not None:
            return f"Already up to date. Version: {yt_up_to_date.group(1)}"
        raise TaskException("Unknown response from pip")
