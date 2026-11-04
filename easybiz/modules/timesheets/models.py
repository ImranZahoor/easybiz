import uuid

from django.db import models


class Project(models.Model):
    """A billable/trackable project; code is stored uppercase and unique."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=200)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class Entry(models.Model):
    """A user's time entry against a project, moving draft → submitted → approved/rejected."""

    DRAFT, SUBMITTED, APPROVED, REJECTED = "draft", "submitted", "approved", "rejected"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(db_index=True)
    project = models.ForeignKey(Project, on_delete=models.PROTECT)
    work_date = models.DateField(db_index=True)
    hours = models.DecimalField(max_digits=4, decimal_places=2)
    note = models.CharField(max_length=300, blank=True, default="")
    status = models.CharField(max_length=10, db_index=True, default=DRAFT)
    reviewed_by = models.UUIDField(null=True, blank=True)
    review_note = models.CharField(max_length=300, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(hours__gt=0) & models.Q(hours__lte=24),
                name="timesheets_hours_range",
            )
        ]
