@echo off
SETLOCAL EnableDelayedExpansion
SETLOCAL ENABLEEXTENSIONS
set ffmpegoptions=-an -vcodec libx264 -tune animation -preset veryslow -movflags faststart -pix_fmt yuv420p -vf "scale='min(1280,iw)':'min(1280,ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2" -profile:v baseline -level 3.0 -vsync vfr
set crf=18
set limit=8000000
set targetsize=8
set original_dir=%cd%
for %%a in (%*) do (
	echo %%a
	if exist %%a (
        if not exist "%%~dpna_compat.mp4" (
            ffmpeg -i %%a %ffmpegoptions% -crf %crf% "%%~dpna_compat.mp4"
            for %%x in ("%%~dpna_compat.mp4") do (
                if %%~zx gtr %limit% (
                    for /F "tokens=* USEBACKQ" %%F IN (`ffprobe -v error -show_entries format^=duration -of default^=noprint_wrappers^=1:nokey^=1 %%a 2^>^&1`) do (
                        ffmpeg -i %%a %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 1 -f mp4 NUL -y
                        ffmpeg -i %%a %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 2 "%%~dpna_compat.mp4" -y
                        del "%%~dpaffmpeg2pass*"
                    )
                )
            )
        )
	)
)
cd %original_dir%
REM timeout 5
pause