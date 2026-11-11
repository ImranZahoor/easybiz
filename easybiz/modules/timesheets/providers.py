from datetime import date
from decimal import Decimal
from uuid import UUID

from easybiz.core.contracts import AttendanceProvider
from easybiz.core.kernel import capabilities
from easybiz.modules.timesheets import queries


class TimesheetsAttendance:
    """Sums a user's approved hours within a date range (AttendanceProvider)."""

    def approved_hours(self, user_id: UUID, start: date, end: date) -> Decimal:
        return queries.approved_hours(user_id, start, end)


capabilities.register(AttendanceProvider, TimesheetsAttendance(), "timesheets", version="1.0.0")
