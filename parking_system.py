from __future__ import annotations

import uuid
from typing import Optional, Tuple

from heap_allocator import ParkingSpotHeap
from models import ParkingSpot, Reservation, SpotStatus, ReservationStatus
from queue_gate import Queue, CircularQueue
from stack_undo import Stack, UndoOp


class ParkingSystem:
    """
    駐車場予約システムの中枢

    - 空き区画: type別 Min-Heap
    - 入庫待ち: Queue（FIFO）
    - ゲート割当: Circular Queue（Round-robin）
    - Undo: Stack（LIFO）
    """

    def __init__(self) -> None:
        self.spots: list[ParkingSpot] = []
        self.reservations: dict[str, Reservation] = {}

        self.available_normal = ParkingSpotHeap()
        self.available_ev = ParkingSpotHeap()

        self.entry_queue: Queue[str] = Queue()
        self._queued_set: set[str] = set()

        self.gates: CircularQueue[str] = CircularQueue(capacity=3)
        for name in ["Gate1", "Gate2", "Gate3"]:
            self.gates.enqueue(name)

        # Undo Stack
        self.undo_stack: Stack[UndoOp] = Stack()

    # -------------------------
    # 初期化
    # -------------------------
    def initialize_spots(self) -> None:
        self.spots.clear()
        self.reservations.clear()

        self.available_normal = ParkingSpotHeap()
        self.available_ev = ParkingSpotHeap()

        self.entry_queue = Queue()
        self._queued_set = set()

        self.gates = CircularQueue(capacity=3)
        for name in ["Gate1", "Gate2", "Gate3"]:
            self.gates.enqueue(name)

        self.undo_stack = Stack()

        for floor in range(1, 4):
            for i in range(1, 21):
                spot_id = f"F{floor}-{i:03d}"
                spot_type = "EV" if i <= 5 else "normal"

                spot = ParkingSpot(
                    spot_id=spot_id,
                    floor=floor,
                    spot_type=spot_type,
                    status=SpotStatus.EMPTY,
                )
                self.spots.append(spot)

                if spot_type == "EV":
                    self.available_ev.add_spot(spot)
                else:
                    self.available_normal.add_spot(spot)

    # -------------------------
    # 表示用
    # -------------------------
    def list_reservations(self, status: ReservationStatus | None = None) -> list[Reservation]:
        items = list(self.reservations.values())
        if status is None:
            return items
        return [r for r in items if r.status == status]

    def list_history(self) -> list[Reservation]:
        # 「履歴」は CANCELED / DONE とする（必要ならここで増やせる）
        return [
            r for r in self.reservations.values()
            if r.status in (ReservationStatus.CANCELED, ReservationStatus.DONE)
        ]

    def get_available_counts(self) -> dict[str, int]:
        return {"normal": self.available_normal.size(), "EV": self.available_ev.size()}

    def get_entry_queue_size(self) -> int:
        return self.entry_queue.size()

    def get_spot_by_id(self, spot_id: str) -> Optional[ParkingSpot]:
        for s in self.spots:
            if s.spot_id == spot_id:
                return s
        return None

    # -------------------------
    # 予約
    # -------------------------
    def reserve(
        self,
        username: str,
        license_plate: str,
        start_time: int,
        end_time: int,
        spot_type: str = "normal",
    ) -> Optional[Reservation]:
        username = (username or "").strip()
        if not username:
            return None

        license_plate = license_plate.strip()
        if not license_plate:
            return None
        if start_time >= end_time:
            return None

        heap = self._select_heap(spot_type)
        if heap is None:
            return None

        spot = heap.pop_best_spot()
        if spot is None:
            return None

        spot.status = SpotStatus.RESERVED

        reservation_id = self._new_reservation_id()
        r = Reservation(
            reservation_id=reservation_id,
            username=username,              # ★追加
            license_plate=license_plate,
            spot_id=spot.spot_id,
            start_time=start_time,
            end_time=end_time,
            status=ReservationStatus.RESERVATION,  # 予約直後
            gate=None,
        )
        self.reservations[reservation_id] = r

        # Undo記録（予約を取り消す）
        self.undo_stack.push(UndoOp(op_type="RESERVE", reservation_id=reservation_id))
        return r

    def cancel_reservation(self, reservation_id: str) -> bool:
        r = self.reservations.get(reservation_id)
        if r is None:
            return False

        # RESERVATION / WAITING のみキャンセル可（ACTIVEは入庫済み）
        if r.status not in (ReservationStatus.RESERVATION, ReservationStatus.WAITING):
            return False

        spot = self.get_spot_by_id(r.spot_id)
        if spot is None:
            return False

        # WAITING なら入庫待ちから外す（実Queueはスキップ方式）
        if reservation_id in self._queued_set:
            self._queued_set.remove(reservation_id)

        if spot.status == SpotStatus.OCCUPIED:
            return False

        r.status = ReservationStatus.CANCELED
        spot.status = SpotStatus.EMPTY

        heap = self._select_heap(spot.spot_type)
        if heap is None:
            return False
        heap.add_spot(spot)

        # Undo記録（キャンセルを取り消す）
        self.undo_stack.push(UndoOp(op_type="CANCEL", reservation_id=reservation_id))
        return True

    # -------------------------
    # 入庫（Queueへ）
    # -------------------------
    def request_check_in(self, reservation_id: str) -> Tuple[bool, str]:
        r = self.reservations.get(reservation_id)
        if r is None:
            return False, "予約が存在しません"
        if r.status != ReservationStatus.RESERVATION:
            return False, "RESERVATIONの予約ではありません"

        spot = self.get_spot_by_id(r.spot_id)
        if spot is None:
            return False, "区画が見つかりません"
        if spot.status != SpotStatus.RESERVED:
            return False, "区画がRESERVEDではありません"

        if reservation_id in self._queued_set:
            return False, "すでに入庫待ちに入っています"

        self.entry_queue.enqueue(reservation_id)
        self._queued_set.add(reservation_id)

        # 入庫待ちへ（Queueに入った状態）
        r.status = ReservationStatus.WAITING

        # Undo記録（受付を取り消す）
        self.undo_stack.push(UndoOp(op_type="REQUEST_CHECKIN", reservation_id=reservation_id))
        return True, "入庫待ちに追加しました（FIFO）"

    def process_next_check_in(self) -> Tuple[bool, str]:
        rid = self.entry_queue.dequeue()
        if rid is None:
            return False, "入庫待ちが空です"

        if rid not in self._queued_set:
            return False, "この入庫待ちはキャンセル済みです（スキップ）"
        self._queued_set.remove(rid)

        r = self.reservations.get(rid)
        if r is None or r.status != ReservationStatus.WAITING:
            return False, "予約が無効です（スキップ）"

        spot = self.get_spot_by_id(r.spot_id)
        if spot is None or spot.status != SpotStatus.RESERVED:
            return False, "区画状態が不正です（スキップ）"

        gate = self.gates.dequeue()
        if gate is None:
            return False, "ゲートが利用できません"

        # Round-robin
        self.gates.enqueue(gate)

        spot.status = SpotStatus.OCCUPIED
        r.gate = gate
        r.status = ReservationStatus.ACTIVE  # 入庫完了

        # Undo記録（入庫処理を取り消す）
        self.undo_stack.push(UndoOp(op_type="PROCESS_CHECKIN", reservation_id=rid))
        return True, f"入庫処理完了：{rid}（{gate}）"

    # -------------------------
    # 出庫
    # -------------------------
    def check_out(self, reservation_id: str, hourly_rate: int = 100) -> Optional[int]:
        r = self.reservations.get(reservation_id)
        if r is None or r.status != ReservationStatus.ACTIVE:
            return None

        spot = self.get_spot_by_id(r.spot_id)
        if spot is None or spot.status != SpotStatus.OCCUPIED:
            return None

        hours = max(0, r.end_time - r.start_time)
        fee = hours * hourly_rate

        r.status = ReservationStatus.DONE
        spot.status = SpotStatus.EMPTY

        heap = self._select_heap(spot.spot_type)
        if heap is None:
            return None
        heap.add_spot(spot)

        # Undo記録（出庫を取り消す）
        self.undo_stack.push(UndoOp(op_type="CHECKOUT", reservation_id=reservation_id))
        return fee

    # -------------------------
    # Undo（直前1操作だけ取り消す）
    # -------------------------
    def undo_last(self) -> Tuple[bool, str]:
        op = self.undo_stack.pop()
        if op is None:
            return False, "Undoできる操作がありません"

        rid = op.reservation_id
        r = self.reservations.get(rid)

        # ---- 予約の取り消し ----
        if op.op_type == "RESERVE":
            if r is None:
                return False, "予約が見つかりません"
            spot = self.get_spot_by_id(r.spot_id)
            if spot is None:
                return False, "区画が見つかりません"

            if spot.status != SpotStatus.RESERVED:
                return False, "この予約はすでに進行しているためUndoできません"

            if rid in self._queued_set:
                self._queued_set.remove(rid)

            del self.reservations[rid]

            spot.status = SpotStatus.EMPTY
            self._select_heap(spot.spot_type).add_spot(spot)

            return True, f"Undo: 予約を取り消しました（{rid}）"

        # ---- キャンセルの取り消し ----
        if op.op_type == "CANCEL":
            if r is None or r.status != ReservationStatus.CANCELED:
                return False, "キャンセル状態ではないためUndoできません"
            spot = self.get_spot_by_id(r.spot_id)
            if spot is None:
                return False, "区画が見つかりません"
            if spot.status != SpotStatus.EMPTY:
                return False, "区画が空きではないためUndoできません"

            r.status = ReservationStatus.RESERVATION
            spot.status = SpotStatus.RESERVED
            return True, f"Undo: キャンセルを取り消しました（{rid}）"

        # ---- 入庫受付の取り消し ----
        if op.op_type == "REQUEST_CHECKIN":
            if rid in self._queued_set:
                self._queued_set.remove(rid)
                if r is not None and r.status == ReservationStatus.WAITING:
                    r.status = ReservationStatus.RESERVATION
                return True, f"Undo: 入庫受付を取り消しました（{rid}）"
            return False, "入庫待ちに存在しないためUndoできません"

        # ---- 入庫処理（OCCUPIED化）の取り消し ----
        if op.op_type == "PROCESS_CHECKIN":
            if r is None or r.status != ReservationStatus.ACTIVE:
                return False, "予約が無効です"
            spot = self.get_spot_by_id(r.spot_id)
            if spot is None:
                return False, "区画が見つかりません"
            if spot.status != SpotStatus.OCCUPIED:
                return False, "入庫済みではないためUndoできません"

            spot.status = SpotStatus.RESERVED
            r.gate = None
            r.status = ReservationStatus.WAITING

            self.entry_queue.enqueue_front(rid)
            self._queued_set.add(rid)

            n = self.gates.size()
            for _ in range(max(0, n - 1)):
                g = self.gates.dequeue()
                if g is not None:
                    self.gates.enqueue(g)

            return True, f"Undo: 入庫処理を取り消しました（{rid}）"

        # ---- 出庫（DONE化）の取り消し ----
        if op.op_type == "CHECKOUT":
            if r is None or r.status != ReservationStatus.DONE:
                return False, "DONE状態ではないためUndoできません"
            spot = self.get_spot_by_id(r.spot_id)
            if spot is None:
                return False, "区画が見つかりません"
            if spot.status != SpotStatus.EMPTY:
                return False, "区画が空きではないためUndoできません"

            r.status = ReservationStatus.ACTIVE
            spot.status = SpotStatus.OCCUPIED
            return True, f"Undo: 出庫を取り消しました（{rid}）"

        return False, "未対応のUndo操作です"

    # -------------------------
    # 内部
    # -------------------------
    def _select_heap(self, spot_type: str) -> Optional[ParkingSpotHeap]:
        if spot_type == "EV":
            return self.available_ev
        if spot_type == "normal":
            return self.available_normal
        return None

    def _new_reservation_id(self) -> str:
        return f"R-{uuid.uuid4().hex[:8]}"
