import uuid

from django.db import models
from django_tenants.models import DomainMixin, TenantMixin


class Tenant(TenantMixin):
    """One customer organisation; owns one PostgreSQL schema."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=40, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    auto_create_schema = True
    auto_drop_schema = False


class Domain(DomainMixin):
    """A host name mapped to a tenant."""


class PlatformAuditLog(models.Model):
    """An operator action on the platform, recorded in the public schema."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor_id = models.UUIDField(null=True, blank=True)
    actor_email = models.CharField(max_length=254, blank=True, default="")
    action = models.CharField(max_length=64, db_index=True)
    target = models.CharField(max_length=120, blank=True, default="", db_index=True)
    detail = models.JSONField(default=dict)
