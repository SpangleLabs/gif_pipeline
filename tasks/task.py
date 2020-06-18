from abc import ABC, abstractmethod
from typing import TypeVar, Generic

T = TypeVar('T')


class Task(ABC, Generic[T]):

    @abstractmethod
    async def run(self) -> T:
        pass
