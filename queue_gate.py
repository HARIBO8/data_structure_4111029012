from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Optional, TypeVar, List

T = TypeVar("T")


@dataclass
class _Node(Generic[T]):
    value: T
    next: Optional["_Node[T]"] = None


class Queue(Generic[T]):
    """
    単方向リンクで実装した Queue（FIFO）
    enqueue/dequeue: O(1)

    ※ Undoのために enqueue_front（先頭に戻す）も追加
    """

    def __init__(self) -> None:
        self._head: Optional[_Node[T]] = None
        self._tail: Optional[_Node[T]] = None
        self._size: int = 0

    def enqueue(self, item: T) -> None:
        node = _Node(value=item)
        if self._tail is None:
            self._head = node
            self._tail = node
        else:
            self._tail.next = node
            self._tail = node
        self._size += 1

    def enqueue_front(self, item: T) -> None:
        """
        先頭に追加（Undo用）
        """
        node = _Node(value=item, next=self._head)
        self._head = node
        if self._tail is None:
            self._tail = node
        self._size += 1

    def dequeue(self) -> Optional[T]:
        if self._head is None:
            return None
        node = self._head
        self._head = node.next
        if self._head is None:
            self._tail = None
        self._size -= 1
        return node.value

    def peek(self) -> Optional[T]:
        return None if self._head is None else self._head.value

    def size(self) -> int:
        return self._size

    def is_empty(self) -> bool:
        return self._size == 0


class CircularQueue(Generic[T]):
    """
    配列リングバッファの Circular Queue（Round-robin）
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be > 0")
        self._capacity = capacity
        self._buf: List[Optional[T]] = [None] * capacity
        self._head = 0
        self._tail = 0
        self._count = 0

    def enqueue(self, item: T) -> bool:
        if self.is_full():
            return False
        self._buf[self._tail] = item
        self._tail = (self._tail + 1) % self._capacity
        self._count += 1
        return True

    def dequeue(self) -> Optional[T]:
        if self.is_empty():
            return None
        item = self._buf[self._head]
        self._buf[self._head] = None
        self._head = (self._head + 1) % self._capacity
        self._count -= 1
        return item

    def size(self) -> int:
        return self._count

    def is_empty(self) -> bool:
        return self._count == 0

    def is_full(self) -> bool:
        return self._count == self._capacity
