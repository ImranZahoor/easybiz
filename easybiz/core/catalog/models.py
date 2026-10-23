from django.db import models


class Module(models.Model):
    """System-wide record of an installed module (its parsed manifest)."""

    id = models.CharField(max_length=32, primary_key=True)
    name = models.CharField(max_length=200)
    version = models.CharField(max_length=20)
    manifest = models.JSONField()
    installed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class TenantModule(models.Model):
    """Per-tenant enablement state for a module."""

    ENABLING, ENABLED, DISABLED = "enabling", "enabled", "disabled"
    STATUS = [(ENABLING, ENABLING), (ENABLED, ENABLED), (DISABLED, DISABLED)]

    tenant = models.ForeignKey("tenancy.Tenant", on_delete=models.CASCADE, related_name="modules")
    module = models.ForeignKey(Module, on_delete=models.PROTECT)
    status = models.CharField(max_length=10, choices=STATUS)
    installed_version = models.CharField(max_length=20)
    enabled_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["tenant", "module"], name="uniq_tenant_module")
        ]


class Permission(models.Model):
    """Assignable permission code; null module = core permission."""

    code = models.CharField(max_length=100, primary_key=True)
    module = models.ForeignKey(Module, on_delete=models.CASCADE, null=True, blank=True)
    description = models.CharField(max_length=300, blank=True)
