import asyncio
import logging
from abc import ABC, abstractmethod
from asyncio import StreamReader
from asyncio.subprocess import Process
from typing import TypeVar, Generic, Optional, Tuple

T = TypeVar('T')
logger = logging.getLogger(__name__)
DEFAULT_TIMEOUT = 5 * 60
CLOSE_TIMEOUT = 10


class TaskException(Exception):
    pass


async def log_output(proc: Process, timeout: int = DEFAULT_TIMEOUT) -> Tuple[str, str]:
    return await asyncio.gather(
        log_stream(proc.stdout, timeout, "stdout"),
        log_stream(proc.stderr, timeout, "stderr")
    )


async def log_stream(stream: StreamReader, timeout: int = DEFAULT_TIMEOUT, prefix: Optional[str] = None) -> str:
    lines = []
    if prefix is None:
        prefix = ""
    else:
        prefix += ": "
    try:
        while True:
            line_bytes = await asyncio.wait_for(stream.readline(), timeout)
            if line_bytes == b"":
                # EOF reached
                break
            line = line_bytes.decode().strip()
            logger.info(prefix + line)
            lines.append(line)
    except asyncio.TimeoutError:
        logger.info(f"STREAM ENDING {prefix}")
    return "\n".join(lines)


async def run_subprocess(args, timeout: int = DEFAULT_TIMEOUT) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(log_output(proc), timeout=timeout)
        # A short timeout to close the subprocess, because the above should have ran it to completion.
        await asyncio.wait_for(proc.communicate(), timeout=CLOSE_TIMEOUT)
        return_code = proc.returncode
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except OSError:
            pass
        raise TaskException("Task timed out")
    if return_code != 0:
        raise TaskException(f"Task returned exit code {return_code}. stderr: {stderr}")
    return stdout


class Task(ABC, Generic[T]):

    @abstractmethod
    async def run(self) -> T:
        pass
