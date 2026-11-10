from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol, runtime_checkable
from uuid import UUID


@runtime_checkable
class AttendanceProvider(Protocol):
    """Approved working hours for a user in a date range (provided by Timesheets)."""

    __contract_version__ = "1.0.0"

    def approved_hours(self, user_id: UUID, start: date, end: date) -> Decimal: ...
