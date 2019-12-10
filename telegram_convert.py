import os

import ffmpy

ffmpegoptions = "-an -vcodec libx264 -tune animation -preset veryslow -movflags faststart -pix_fmt yuv420p -vf \"scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2\" -profile:v baseline -level 3.0 -vsync vfr"
crf = 18
limit = 8000000
targetsize = 8

input_filename = "video_gif"
output_filename = "video_compat.mp4"

null_output = "/dev/null"

# Turn file into mp4
ff = ffmpy.FFmpeg(
    inputs={input_filename: None},
    outputs={output_filename: ffmpegoptions + " -crf" + str(crf)}
)
ff.run()

if os.path.getsize(output_filename) > limit:
    ffprobe = ffmpy.FFprobe(
        global_options=["-v error"],
        inputs={output_filename: "-show_entries format^=duration -of default^=noprint_wrappers^=1:nokey^=1"}
    )
    duration = ffprobe.run()[0]
    # 2 pass run
    bitrate = targetsize / duration * 1000000 * 8
    ff1 = ffmpy.FFmpeg(
        global_options=["-y"],
        inputs={input_filename: None},
        outputs={null_output: ffmpegoptions + " -b:v " + str(bitrate) + " -pass 1 -f mp4"}
    )
    ff1.run()
    ff2 = ffmpy.FFmpeg(
        global_options=["-y"],
        inputs={input_filename: None},
        outputs={output_filename: ffmpegoptions + " -b:v " + str(bitrate) + " -pass 2"}
    )
    ff2.run()
