import asyncio
import json
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
                logger.debug("Stream ended %s", prefix)
                break
            line = line_bytes.decode().strip()
            logger.info(prefix + line)
            lines.append(line)
    except asyncio.TimeoutError:
        logger.error("STREAM TIMEOUT %s", prefix)
    return "\n".join(lines)


async def run_subprocess(args, timeout: int = DEFAULT_TIMEOUT) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args,
        limit=1024 * 1024 * 5,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    logger.debug("Running subprocess: %s", args)
    try:
        stdout, stderr = await asyncio.wait_for(log_output(proc), timeout=timeout)
        # A short timeout to close the subprocess, because the above should have ran it to completion.
        await asyncio.wait_for(proc.communicate(), timeout=CLOSE_TIMEOUT)
        return_code = proc.returncode
    except asyncio.TimeoutError:
        logger.error("Subprocess timed out, killing: %s", args)
        try:
            proc.kill()
        except OSError:
            pass
        raise TaskException("Task timed out")
    if return_code != 0:
        logger.warning("Subprocess returned exit code %s: %s", return_code, args)
        raise TaskException(f"Task returned exit code {return_code}. stderr: {stderr}")
    return stdout


class Task(ABC, Generic[T]):

    def __init__(self, *, description: str = None) -> None:
        self.description = description

    @abstractmethod
    async def run(self) -> T:
        pass

    @staticmethod
    def _format_arg(name: str, value: object) -> str:
        return f"{name}={json.dumps(value)}"

    def _format_args(self, args: dict[str, object]) -> list[str]:
        return [
            self._format_arg(k, v) for k, v in args.items()
        ]

    def _format_non_null_args(self, args: dict[str, Optional[object]]) -> list[str]:
        return [
            self._format_arg(k, v) for k, v in args.items() if v is not None
        ]

    @abstractmethod
    def _formatted_args(self) -> list[str]:
        raise NotImplementedError

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        args = self._format_args({"description": self.description}) + self._formatted_args()
        args_str = ", ".join(args)
        return f"{class_name}({args_str})"
