from typing import Generic, List, Optional, TypeVar

T = TypeVar("T")


class RingBuffer(Generic[T]):
    def __init__(self, size: int) -> None:
        self._size = size
        self._buf: List[Optional[T]] = [None] * size
        self._idx = 0
        self._count = 0

    def push(self, item: T) -> None:
        self._buf[self._idx] = item
        self._idx = (self._idx + 1) % self._size
        if self._count < self._size:
            self._count += 1

    def values(self) -> List[T]:
        if self._count == 0:
            return []
        start = self._idx if self._count == self._size else 0
        result: List[T] = []
        for i in range(self._count):
            value = self._buf[(start + i) % self._size]
            if value is not None:
                result.append(value)
        return result

    def update_last(self, item: T) -> None:
        if self._count == 0:
            self.push(item)
            return
        last_index = (self._idx - 1) % self._size
        self._buf[last_index] = item

    def length(self) -> int:
        return self._count
