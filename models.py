from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class SpotStatus(Enum):
    EMPTY = "EMPTY"
    RESERVED = "RESERVED"
    OCCUPIED = "OCCUPIED"


@dataclass
class ParkingSpot:
    spot_id: str
    floor: int
    spot_type: str      # "normal" / "EV"
    status: SpotStatus


class ReservationStatus(Enum):
    RESERVATION = "RESERVATION"
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    CANCELED = "CANCELED"
    DONE = "DONE"


@dataclass
class Reservation:
    reservation_id: str
    username: str              # ★追加：この予約の所有ユーザー
    license_plate: str
    spot_id: str
    start_time: int
    end_time: int
    status: ReservationStatus
    gate: Optional[str] = None  # 入庫処理時に割り当てたゲート
