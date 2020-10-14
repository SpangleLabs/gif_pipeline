import subprocess

import ffmpy3

from tasks.task import Task


class FfmpegTask(Task[str]):

    def __init__(self, *, global_options=None, inputs=None, outputs=None):
        self.global_options = global_options
        self.inputs = inputs
        self.outputs = outputs

    async def run(self):
        ff = ffmpy3.FFmpeg(
            global_options=self.global_options,
            inputs=self.inputs,
            outputs=self.outputs
        )
        ff_process = await ff.run_async(stdout=subprocess.PIPE)
        ff_out = await ff_process.communicate()
        await ff.wait()
        output = ff_out[0].decode('utf-8').strip()
        return output
