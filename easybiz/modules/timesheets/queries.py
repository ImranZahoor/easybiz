from datetime import date
from decimal import Decimal
from uuid import UUID

from django.db.models import QuerySet, Sum

from easybiz.modules.timesheets.models import Entry, Project


def all_projects() -> QuerySet[Project]:
    return Project.objects.order_by("code")


def project_exists(code: str) -> bool:
    return Project.objects.filter(code=code).exists()


def active_project(project_id: UUID) -> Project | None:
    return Project.objects.filter(id=project_id, is_active=True).first()


def entry(entry_id: UUID) -> Entry | None:
    return Entry.objects.filter(id=entry_id).first()


def own_entry(user_id: UUID, entry_id: UUID) -> Entry | None:
    return Entry.objects.filter(id=entry_id, user_id=user_id).first()


def entries_for(
    viewer_id: UUID, can_view_all: bool, status: str | None = None, user_id: UUID | None = None
) -> QuerySet[Entry]:
    """A reader sees only their own entries; an approver sees all, optionally filtered by user."""
    entries = Entry.objects.all()
    if can_view_all:
        if user_id:
            entries = entries.filter(user_id=user_id)
    else:
        entries = entries.filter(user_id=viewer_id)
    if status:
        entries = entries.filter(status=status)
    return entries.order_by("-work_date")


def approved_hours(user_id: UUID, start: date, end: date) -> Decimal:
    total = Entry.objects.filter(
        user_id=user_id, status=Entry.APPROVED, work_date__gte=start, work_date__lte=end
    ).aggregate(total=Sum("hours"))["total"]
    return total or Decimal("0")
