from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Optional, TypeVar, List

T = TypeVar("T")


class Stack(Generic[T]):
    """
    Stack（LIFO）
    push: O(1)
    pop : O(1)
    """

    def __init__(self) -> None:
        self._data: List[T] = []

    def push(self, item: T) -> None:
        self._data.append(item)

    def pop(self) -> Optional[T]:
        if not self._data:
            return None
        return self._data.pop()

    def peek(self) -> Optional[T]:
        if not self._data:
            return None
        return self._data[-1]

    def size(self) -> int:
        return len(self._data)

    def is_empty(self) -> bool:
        return self.size() == 0


@dataclass
class UndoOp:
    """
    直前操作を取り消すための記録
    """
    op_type: str
    reservation_id: str
