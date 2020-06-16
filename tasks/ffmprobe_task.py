import subprocess

import ffmpy3

from tasks.task import Task


class FFprobeTask(Task[str]):

    def __init__(self, *, global_options=None, inputs=None, outputs=None):
        self.global_options = global_options
        self.inputs = inputs
        self.outputs = outputs

    async def run(self) -> str:
        ffprobe = ffmpy3.FFprobe(
            global_options=self.global_options,
            inputs=self.inputs
        )
        ffprobe_process = await ffprobe.run_async(stdout=subprocess.PIPE)
        ffprobe_out = await ffprobe_process.communicate()
        await ffprobe.wait()
        output = ffprobe_out[0].decode('utf-8').strip()
        return output
