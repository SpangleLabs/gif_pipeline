@echo off
SETLOCAL EnableDelayedExpansion
SETLOCAL ENABLEEXTENSIONS
set ffmpegoptions=-an -vcodec libx264 -tune animation -preset veryslow -movflags faststart -pix_fmt yuv420p -vf "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2" -profile:v baseline -level 3.0 -vsync vfr
set crf=18
set limit=8000000
set targetsize=8
set original_dir=%cd%
for %%a in (%*) do (
	echo %%a
	if exist %%a\* (
		echo Directory
		cd "%%a"
		for /R %%z in (*.mp4) do (
			echo %%z
			if not exist "%%~dpnz_compat.mp4" (
				REM ffmpeg -i "%%z" %ffmpegoptions% -crf %crf% "%%~dpnz_compat.mp4"
				for %%x in (%%~dpnz_compat.mp4) do (
					if %%~zx gtr %limit% (
						for /F "tokens=* USEBACKQ" %%F IN (`ffprobe -v error -show_entries format^=duration -of default^=noprint_wrappers^=1:nokey^=1 %%z 2^>^&1`) do (
							REM ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 1 -f mp4 NUL -y
							REM ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 2 "%%~dpnz_compat.mp4" -y
							REM del "%%~dpzffmpeg2pass*"
						)
					)
				)
				REM del "%%z"
				REM ren "%%z" "DONE_%%~nxz"
			)
		)
		for /R %%z in (*.gif) do (
			echo %%z
			if not exist "%%~dpnz.mp4" (
				ffmpeg -i "%%z" %ffmpegoptions% -crf %crf% "%%~dpnz.mp4"
				for %%x in (%%~dpnz.mp4) do (
					if %%~zx gtr %limit% (
						for /F "tokens=* USEBACKQ" %%F IN (`ffprobe -v error -show_entries format^=duration -of default^=noprint_wrappers^=1:nokey^=1 %%z 2^>^&1`) do (
							ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 1 -f mp4 NUL -y
							ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 2 "%%~dpnz.mp4" -y
							del "%%~dpzffmpeg2pass*"
						)
					)
				)
				REM del "%%z"
				REM ren "%%z" "DONE_%%~nxz"
			)
		)
		for /R %%z in (*.mov) do (
			echo %%z
			if not exist "%%~dpnz.mp4" (
				ffmpeg -i "%%z" %ffmpegoptions% -crf %crf% "%%~dpnz.mp4"
				for %%x in (%%~dpnz.mp4) do (
					if %%~zx gtr %limit% (
						for /F "tokens=* USEBACKQ" %%F IN (`ffprobe -v error -show_entries format^=duration -of default^=noprint_wrappers^=1:nokey^=1 %%z 2^>^&1`) do (
							ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 1 -f mp4 NUL -y
							ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 2 "%%~dpnz.mp4" -y
							del "%%~dpzffmpeg2pass*"
						)
					)
				)
				REM del "%%z"
				REM ren "%%z" "DONE_%%~nxz"
			)
		)
		for /R %%z in (*.webm) do (
			echo %%z
			if not exist "%%~dpnz.mp4" (
				ffmpeg -i "%%z" %ffmpegoptions% -crf %crf% "%%~dpnz.mp4"
				echo %%~dpnz.mp4
				for %%x in (%%~dpnz.mp4) do (
					if %%~zx gtr %limit% (
						for /F "tokens=* USEBACKQ" %%F IN (`ffprobe -v error -show_entries format^=duration -of default^=noprint_wrappers^=1:nokey^=1 %%z 2^>^&1`) do (
							ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 1 -f mp4 NUL -y
							ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 2 "%%~dpnz.mp4" -y
							del "%%~dpzffmpeg2pass*"
						)
					)
				)
				REM del "%%z"
				REM ren "%%z" "DONE_%%~nxz"
			)
		)
		for /R %%z in (*.flv) do (
			echo %%z
			if not exist "%%~dpnz.mp4" (
				ffmpeg -i "%%z" %ffmpegoptions% -crf %crf% "%%~dpnz.mp4"
				for %%x in (%%~dpnz.mp4) do (
					if %%~zx gtr %limit% (
						for /F "tokens=* USEBACKQ" %%F IN (`ffprobe -v error -show_entries format^=duration -of default^=noprint_wrappers^=1:nokey^=1 %%z 2^>^&1`) do (
							ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 1 -f mp4 NUL -y
							ffmpeg -i "%%z" %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 2 "%%~dpnz.mp4" -y
							del "%%~dpzffmpeg2pass*"
						)
					)
				)
				REM del "%%z"
				REM ren "%%z" "DONE_%%~nxz"
			)
		)
	) else if exist %%a (
		set FILE=%%~fa
		set EXT=!FILE:~-4!
		if /I "!EXT!" == ".mp4" (
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
				REM del %%a
				REM mkdir "%%~dpaDONE"
				REM move %%a "%%~dpaDONE"
				REM ren %%a "_DONE%%~nxa"
			)
		) else (
			if not exist "%%~dpna.mp4" (
				ffmpeg -i %%a %ffmpegoptions% -crf %crf% "%%~dpna.mp4"
				for %%x in ("%%~dpna.mp4") do (
					if %%~zx gtr %limit% (
						for /F "tokens=* USEBACKQ" %%F IN (`ffprobe -v error -show_entries format^=duration -of default^=noprint_wrappers^=1:nokey^=1 %%a 2^>^&1`) do (
							ffmpeg -i %%a %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 1 -f mp4 NUL -y
							ffmpeg -i %%a %ffmpegoptions% -b:v %targetsize%/%%F*1000000*8 -pass 2 "%%~dpna.mp4" -y
							del "%%~dpaffmpeg2pass*"
						)
					)
				)
				REM del %%a
				REM mkdir "%%~dpaDONE"
				REM move %%a "%%~dpaDONE"
				REM ren %%a "DONE_%%~nxa"
			)
		)
	)
)
cd %original_dir%
REM timeout 5
pause