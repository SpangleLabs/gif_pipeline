from gif_pipeline.tasks.task import Task, run_subprocess, TaskException
from gif_pipeline.tasks.youtube_dl_task import yt_dl_pkg


class UpdateYoutubeDLTask(Task[str]):

    async def run(self) -> str:
        args = ["pip", "install", yt_dl_pkg, "--upgrade"]
        stdout = await run_subprocess(args)
        lines = stdout.splitlines()
        last_line = lines[-1]
        if last_line.startswith("Successfully installed"):
            updates = last_line.split()
            yt_update = next(filter(lambda u: u.startswith(f"{yt_dl_pkg}-"), updates), None)
            if yt_update:
                return f"Updated {yt_dl_pkg} to {yt_update}"
            return "Updated other packages"
        up_to_date_msg = f"Requirement already up-to-date: {yt_dl_pkg}"
        yt_up_to_date = next(filter(lambda l: l.startswith(up_to_date_msg), lines), None)
        if yt_up_to_date is not None:
            return "Already up to date"
        raise TaskException("Unknown response from pip")
