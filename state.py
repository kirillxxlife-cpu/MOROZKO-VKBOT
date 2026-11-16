import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional

class SlotStatus(str, Enum):
    FREE = "free"
    HOLD = "hold"
    BOOKED = "booked"

@dataclass
class Slot:
    id: int
    date: date
    time: time
    status: SlotStatus = SlotStatus.FREE
    hold_until: Optional[datetime] = None
    booking_id: Optional[uuid.UUID] = None

@dataclass
class Booking:
    id: uuid.UUID
    vk_id: int
    slot_id: Optional[int]
    package: str = ""
    extras: list = field(default_factory=list)
    children: list = field(default_factory=list)
    address: str = ""
    phone: str = ""
    total: Decimal = Decimal("0")
    status: str = "draft"

@dataclass
class UserState:
    vk_id: int
    step: str = "main"
    draft: dict = field(default_factory=dict)
    operator_mode: bool = False
    name: str = ""
    ai_history: list = field(default_factory=list)

_lock = asyncio.Lock()
_users: dict[int, UserState] = {}
_slots: dict[int, Slot] = {}
_bookings: dict[uuid.UUID, Booking] = {}
_next_slot_id = 1

PACKAGE_PRICES = {"mini": Decimal("3500"), "standard": Decimal("5500"), "premium": Decimal("8500")}
PACKAGE_NAMES = {"mini": "Мини", "standard": "Стандарт", "premium": "Премиум"}
EXTRA_PRICES = {"photo": Decimal("2000"), "cake": Decimal("1500"), "balls": Decimal("800")}
EXTRA_NAMES = {"photo": "Фотограф", "cake": "Торт", "balls": "Шары"}

def init_slots(days_ahead: int = 14) -> None:
    global _next_slot_id
    today = date.today()
    times = [time(h, 0) for h in (10, 12, 14, 16, 18, 20)]
    for offset in range(days_ahead):
        d = today + timedelta(days=offset)
        for t in times:
            _slots[_next_slot_id] = Slot(id=_next_slot_id, date=d, time=t)
            _next_slot_id += 1

def mark_booked_from_sheets(rows: list[dict]) -> int:
    restored = 0
    for row in rows:
        try:
            # Ожидаем формат даты ДД.ММ.ГГГГ из таблицы
            d = datetime.strptime(row["Дата"], "%d.%m.%Y").date()
            hh, mm = row["Время"].split(":")
            t = time(int(hh), int(mm))
        except Exception:
            continue
        for s in _slots.values():
            if s.date == d and s.time == t and s.status == SlotStatus.FREE:
                s.status = SlotStatus.BOOKED
                restored += 1
                break
    return restored

def get_user(vk_id: int) -> UserState:
    if vk_id not in _users:
        _users[vk_id] = UserState(vk_id=vk_id)
    return _users[vk_id]

def _cleanup_expired_now() -> None:
    now = datetime.now(timezone.utc)
    for s in _slots.values():
        if s.status == SlotStatus.HOLD and s.hold_until and s.hold_until < now:
            s.status = SlotStatus.FREE
            s.hold_until = None
            s.booking_id = None

def get_free_slots_by_date(d: date) -> list[Slot]:
    _cleanup_expired_now()
    return sorted([s for s in _slots.values() if s.date == d], key=lambda s: s.time)

def get_dates_summary(days_ahead: int = 14) -> list[dict]:
    _cleanup_expired_now()
    today = date.today()
    result = []
    for offset in range(days_ahead):
        d = today + timedelta(days=offset)
        day_slots = [s for s in _slots.values() if s.date == d]
        free = sum(1 for s in day_slots if s.status == SlotStatus.FREE)
        result.append({"date": d, "total": len(day_slots), "free": free})
    return result

async def hold_slot(slot_id: int, booking_id: uuid.UUID, hold_minutes: int = 15) -> Optional[Slot]:
    async with _lock:
        slot = _slots.get(slot_id)
        if not slot: return None
        now = datetime.now(timezone.utc)
        if slot.status == SlotStatus.HOLD and slot.hold_until and slot.hold_until < now:
            slot.status = SlotStatus.FREE
            slot.hold_until = None
            slot.booking_id = None
        if slot.status != SlotStatus.FREE: return None
        slot.status = SlotStatus.HOLD
        slot.hold_until = now + timedelta(minutes=hold_minutes)
        slot.booking_id = booking_id
        return slot

async def confirm_booking(booking_id: uuid.UUID) -> bool:
    async with _lock:
        booking = _bookings.get(booking_id)
        if not booking or not booking.slot_id: return False
        slot = _slots.get(booking.slot_id)
        if not slot: return False
        if slot.status == SlotStatus.BOOKED: return True
        if slot.status != SlotStatus.HOLD: return False
        slot.status = SlotStatus.BOOKED
        slot.hold_until = None
        booking.status = "paid"
        return True

def create_booking(vk_id: int, draft: dict) -> Booking:
    total = calc_total(draft)
    b = Booking(
        id=uuid.uuid4(), vk_id=vk_id, slot_id=draft.get("slot_id"),
        package=draft.get("package", ""), extras=list(draft.get("extras", [])),
        children=list(draft.get("children", [])), address=draft.get("address", ""),
        phone=draft.get("phone", ""), total=total,
    )
    _bookings[b.id] = b
    return b

def calc_total(draft: dict) -> Decimal:
    total = PACKAGE_PRICES.get(draft.get("package", ""), Decimal("0"))
    for e in draft.get("extras", []):
        total += EXTRA_PRICES.get(e, Decimal("0"))
    return total

async def cleanup_loop(interval_seconds: int = 60) -> None:
    while True:
        try:
            async with _lock:
                _cleanup_expired_now()
        except Exception:
            pass
        await asyncio.sleep(interval_seconds)
