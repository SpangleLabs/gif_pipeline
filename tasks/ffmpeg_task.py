import ffmpy3

from tasks.task import Task


class FfmpegTask(Task):

    def __init__(self, *, inputs, outputs):
        self.inputs = inputs
        self.outputs = outputs

    async def run(self):
        ff = ffmpy3.FFmpeg(
            inputs=self.inputs,
            outputs=self.outputs
        )
        await ff.run_async()
        await ff.wait()
