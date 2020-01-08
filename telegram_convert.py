import asyncio
import os
import subprocess

import ffmpy3

ffmpegoptions = "-an -vcodec libx264 -tune animation -preset veryslow -movflags faststart -pix_fmt yuv420p -vf \"scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2\" -profile:v baseline -level 3.0 -vsync vfr"
crf = 18
limit = 8000000
targetsize = 8


async def main():
    input_filename = "video.gif"
    output_filename = "video_compat.mp4"

    null_output = os.devnull

    # Turn file into mp4
    ff = ffmpy3.FFmpeg(
        inputs={input_filename: None},
        outputs={output_filename: ffmpegoptions + " -crf " + str(crf)}
    )
    await ff.run_async()
    await ff.wait()

    # If it's over the size limit, do a 2 pass encoding
    if os.path.getsize(output_filename) > limit:
        # Get video duration from ffprobe
        ffprobe = ffmpy3.FFprobe(
            global_options=["-v error"],
            inputs={output_filename: "-show_entries format=duration -of default=noprint_wrappers=1:nokey=1"}
        )
        ffprobe_process = await ffprobe.run_async(stdout=asyncio.subprocess.PIPE)
        ffprobe_out = await ffprobe_process.communicate()
        await ffprobe.wait()
        duration = float(ffprobe_out[0].decode('utf-8').strip())
        # 2 pass run
        bitrate = targetsize / duration * 1000000 * 8
        ff1 = ffmpy3.FFmpeg(
            global_options=["-y"],
            inputs={input_filename: None},
            outputs={null_output: ffmpegoptions + " -b:v " + str(bitrate) + " -pass 1 -f mp4"}
        )
        await ff1.run_async()
        await ff1.wait()
        ff2 = ffmpy3.FFmpeg(
            global_options=["-y"],
            inputs={input_filename: None},
            outputs={output_filename: ffmpegoptions + " -b:v " + str(bitrate) + " -pass 2"}
        )
        await ff2.run_async()
        await ff2.wait()

loop = asyncio.ProactorEventLoop()
asyncio.set_event_loop(loop)
loop.run_until_complete(main())
