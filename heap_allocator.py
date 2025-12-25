from __future__ import annotations

import heapq
from typing import Optional

from models import ParkingSpot, SpotStatus


class ParkingSpotHeap:
    """
    空き区画を管理する Min-Heap
    (spot_id, spot) を入れて spot_id 昇順で取り出す

    ※ undo等で spot.status が変わると、ヒープ内に「古いデータ」が残る可能性がある。
      そのため pop 時に spot.status を確認し、EMPTY 以外は捨てる（lazy deletion）。
    """

    def __init__(self) -> None:
        self._heap: list[tuple[str, ParkingSpot]] = []

    def add_spot(self, spot: ParkingSpot) -> None:
        if spot.status != SpotStatus.EMPTY:
            return
        heapq.heappush(self._heap, (spot.spot_id, spot))

    def pop_best_spot(self) -> Optional[ParkingSpot]:
        """
        最適な空き区画を1つ取り出す（Heapから削除）
        EMPTY でない古い要素が出たら捨てて続行する。
        """
        while self._heap:
            _, spot = heapq.heappop(self._heap)
            if spot.status == SpotStatus.EMPTY:
                return spot
            # 古い要素（RESERVED/OCCUPIED）なので捨てる
        return None

    def size(self) -> int:
        return len(self._heap)

    def is_empty(self) -> bool:
        return self.size() == 0
