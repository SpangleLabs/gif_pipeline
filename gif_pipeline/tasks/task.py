import asyncio
from abc import ABC, abstractmethod
from typing import TypeVar, Generic

T = TypeVar('T')


class TaskException(Exception):
    pass


async def run_subprocess(args) -> str:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5*60)
        return_code = proc.returncode
    except asyncio.exceptions.TimeoutError:
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
