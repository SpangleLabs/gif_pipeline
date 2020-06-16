import ffmpy3

from tasks.task import Task


class FfmpegTask(Task):

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
        await ff.run_async()
        await ff.wait()
