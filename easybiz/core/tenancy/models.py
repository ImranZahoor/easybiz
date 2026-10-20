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
