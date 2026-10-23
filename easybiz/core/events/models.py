import uuid

from django.db import models
from django.utils import timezone


class OutboxEvent(models.Model):
    PENDING, DONE, DEAD = "pending", "done", "dead"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120, db_index=True)
    producer = models.CharField(max_length=32)
    payload = models.JSONField(default=dict)
    version = models.SmallIntegerField(default=1)
    status = models.CharField(max_length=10, default=PENDING, db_index=True)
    attempts = models.SmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.TextField(blank=True)
    parked = models.JSONField(default=list)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)


class InboxProcessed(models.Model):
    event_id = models.UUIDField(db_index=True)
    handler = models.CharField(max_length=160)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["event_id", "handler"], name="uniq_event_handler")
        ]
