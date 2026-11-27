from django.db import models


class IdemKey(models.Model):
    """One client-supplied Idempotency-Key and the response it owns, per tenant schema."""

    key = models.CharField(max_length=200, unique=True)
    endpoint = models.CharField(max_length=200)
    request_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=12)  # "in_progress" | "completed"
    response_status = models.IntegerField(null=True, blank=True)
    body = models.TextField(default="")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
