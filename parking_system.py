from __future__ import annotations

import uuid
from typing import Optional, Tuple

from heap_allocator import ParkingSpotHeap
from models import ParkingSpot, Reservation, SpotStatus, ReservationStatus
from queue_gate import Queue, CircularQueue
from stack_undo import Stack, UndoOp


class ParkingSystem:
    """
    停車場預約系統的核心模組

    - 空車位管理：依類型使用 Min-Heap
    - 入庫等待佇列：Queue（FIFO）
    - 閘門分配：Circular Queue（Round-robin）
    - 操作復原（Undo）：Stack（LIFO）
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
    def list_reservations(self, status: Optional[ReservationStatus] = None) -> list[Reservation]:
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
            username=username,
            license_plate=license_plate,
            spot_id=spot.spot_id,
            start_time=start_time,
            end_time=end_time,
            status=ReservationStatus.RESERVATION,
            gate=None,
        )
        self.reservations[reservation_id] = r

        self.undo_stack.push(UndoOp(op_type="RESERVE", reservation_id=reservation_id))
        return r

    def cancel_reservation(self, reservation_id: str) -> bool:
        r = self.reservations.get(reservation_id)
        if r is None:
            return False

        if r.status not in (ReservationStatus.RESERVATION, ReservationStatus.WAITING):
            return False

        spot = self.get_spot_by_id(r.spot_id)
        if spot is None:
            return False

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

        self.undo_stack.push(UndoOp(op_type="CANCEL", reservation_id=reservation_id))
        return True

    # -------------------------
    # 入庫（Queueへ）
    # -------------------------
    def request_check_in(self, reservation_id: str) -> Tuple[bool, str]:
        r = self.reservations.get(reservation_id)
        if r is None:
            return False, "預約不存在"
        if r.status != ReservationStatus.RESERVATION:
            return False, "此預約狀態並非 RESERVATION"

        spot = self.get_spot_by_id(r.spot_id)
        if spot is None:
            return False, "找不到對應的停車格"
        if spot.status != SpotStatus.RESERVED:
            return False, "停車格狀態不是 RESERVED"

        if reservation_id in self._queued_set:
            return False, "已在入庫等待佇列中"

        self.entry_queue.enqueue(reservation_id)
        self._queued_set.add(reservation_id)

        r.status = ReservationStatus.WAITING

        self.undo_stack.push(UndoOp(op_type="REQUEST_CHECKIN", reservation_id=reservation_id))
        return True, "已加入入庫等待佇列（FIFO）"

    def process_next_check_in(self) -> Tuple[bool, str]:
        rid = self.entry_queue.dequeue()
        if rid is None:
            return False, "目前沒有入庫等待中的車輛"

        if rid not in self._queued_set:
            return False, "此入庫請求已被取消（已略過）"
        self._queued_set.remove(rid)

        r = self.reservations.get(rid)
        if r is None or r.status != ReservationStatus.WAITING:
            return False, "預約狀態無效（已略過）"

        spot = self.get_spot_by_id(r.spot_id)
        if spot is None or spot.status != SpotStatus.RESERVED:
            return False, "停車格狀態異常（已略過）"

        gate = self.gates.dequeue()
        if gate is None:
            return False, "目前沒有可用的入庫閘門"

        self.gates.enqueue(gate)

        spot.status = SpotStatus.OCCUPIED
        r.gate = gate
        r.status = ReservationStatus.ACTIVE

        self.undo_stack.push(UndoOp(op_type="PROCESS_CHECKIN", reservation_id=rid))
        return True, f"入庫完成：{rid}（{gate}）"

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

        self.undo_stack.push(UndoOp(op_type="CHECKOUT", reservation_id=reservation_id))
        return fee

    # -------------------------
    # Undo
    # -------------------------
    def undo_last(self) -> Tuple[bool, str]:
        op = self.undo_stack.pop()
        if op is None:
            return False, "目前沒有可復原的操作"

        rid = op.reservation_id
        r = self.reservations.get(rid)

        if op.op_type == "RESERVE":
            if r is None:
                return False, "找不到對應的預約"
            spot = self.get_spot_by_id(r.spot_id)
            if spot is None:
                return False, "找不到停車格"

            if spot.status != SpotStatus.RESERVED:
                return False, "此預約已進行後續操作，無法復原"

            if rid in self._queued_set:
                self._queued_set.remove(rid)

            del self.reservations[rid]

            spot.status = SpotStatus.EMPTY
            self._select_heap(spot.spot_type).add_spot(spot)

            return True, f"Undo：已取消預約（{rid}）"

        if op.op_type == "CANCEL":
            if r is None or r.status != ReservationStatus.CANCELED:
                return False, "此狀態無法復原"
            spot = self.get_spot_by_id(r.spot_id)
            if spot is None:
                return False, "找不到停車格"
            if spot.status != SpotStatus.EMPTY:
                return False, "停車格非空位，無法復原"

            r.status = ReservationStatus.RESERVATION
            spot.status = SpotStatus.RESERVED
            return True, f"Undo：已復原取消操作（{rid}）"

        if op.op_type == "REQUEST_CHECKIN":
            if rid in self._queued_set:
                self._queued_set.remove(rid)
                if r is not None and r.status == ReservationStatus.WAITING:
                    r.status = ReservationStatus.RESERVATION
                return True, f"Undo：已取消入庫申請（{rid}）"
            return False, "該入庫請求不存在，無法復原"

        if op.op_type == "PROCESS_CHECKIN":
            if r is None or r.status != ReservationStatus.ACTIVE:
                return False, "預約狀態無效"
            spot = self.get_spot_by_id(r.spot_id)
            if spot is None:
                return False, "找不到停車格"
            if spot.status != SpotStatus.OCCUPIED:
                return False, "尚未完成入庫，無法復原"

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

            return True, f"Undo：已取消入庫處理（{rid}）"

        if op.op_type == "CHECKOUT":
            if r is None or r.status != ReservationStatus.DONE:
                return False, "此狀態無法復原"
            spot = self.get_spot_by_id(r.spot_id)
            if spot is None:
                return False, "找不到停車格"
            if spot.status != SpotStatus.EMPTY:
                return False, "停車格非空位，無法復原"

            r.status = ReservationStatus.ACTIVE
            spot.status = SpotStatus.OCCUPIED
            return True, f"Undo：已復原出庫操作（{rid}）"

        return False, "尚未支援的 Undo 操作"

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


    def get_spot_overview(self):
        """
        管理者畫面用：
        依樓層彙整各停車格目前狀態與車輛資訊
        """
        # spot_id -> reservation の対応表
        res_by_spot = {
            r.spot_id: r
            for r in self.reservations.values()
            if r.status in (
                ReservationStatus.RESERVATION,
                ReservationStatus.WAITING,
                ReservationStatus.ACTIVE,
            )
        }

        floors = {}
        for spot in self.spots:
            floor = spot.floor
            floors.setdefault(floor, [])

            r = res_by_spot.get(spot.spot_id)

            floors[floor].append({
                "spot_id": spot.spot_id,
                "status": spot.status.value,
                "username": r.username if r else None,
                "license_plate": r.license_plate if r else None,
            })

        return floors
