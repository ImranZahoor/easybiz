from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db.models import Sum

from easybiz.core.contracts import AttendanceProvider
from easybiz.core.kernel import capabilities
from easybiz.modules.timesheets.models import Entry


class TimesheetsAttendance:
    """Sums a user's approved hours within a date range (AttendanceProvider)."""

    def approved_hours(self, user_id: UUID, start: date, end: date) -> Decimal:
        total = Entry.objects.filter(
            user_id=user_id, status=Entry.APPROVED, work_date__gte=start, work_date__lte=end
        ).aggregate(total=Sum("hours"))["total"]
        return total or Decimal("0")


capabilities.register(AttendanceProvider, TimesheetsAttendance(), "timesheets")
