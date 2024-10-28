import subprocess
from typing import Tuple

import ffmpy3

from gif_pipeline.tasks.task import Task


class FfmpegTask(Task[Tuple[str, str]]):

    def __init__(self, *, global_options=None, inputs=None, outputs=None, description=None) -> None:
        super().__init__(description=description)
        self.global_options = global_options
        self.inputs = inputs
        self.outputs = outputs

    async def run(self) -> Tuple[str, str]:
        ff = ffmpy3.FFmpeg(
            global_options=self.global_options,
            inputs=self.inputs,
            outputs=self.outputs
        )
        ff_process = await ff.run_async(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        ff_out = await ff_process.communicate()
        await ff.wait()
        output = ff_out[0].decode('utf-8', errors="replace").strip()
        error = ff_out[1].decode('utf-8', errors="replace").strip()
        return output, error

    def _formatted_args(self) -> list[str]:
        return self._format_args({
            "global_options": self.global_options,
            "inputs": self.inputs,
            "outputs": self.outputs,
        })
