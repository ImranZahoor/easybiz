import uuid

from django.db import models

from easybiz.core.iam.enums import PolicyEffect


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=300, blank=True)
    is_system = models.BooleanField(default=False)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.SET_NULL, related_name="children"
    )
    created_at = models.DateTimeField(auto_now_add=True)


class RolePermission(models.Model):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions")
    permission = models.CharField(max_length=100)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["role", "permission"], name="uniq_role_permission")
        ]


class UserRole(models.Model):
    user_id = models.UUIDField(db_index=True)  # references users_user by value (I2)
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="assignments")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user_id", "role"], name="uniq_user_role")]


class Policy(models.Model):
    """An ABAC rule: allow/deny a permission when its condition tree matches (F14b)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    permission = models.CharField(max_length=100)  # exact code or a `module.*` group pattern
    effect = models.CharField(max_length=20, choices=PolicyEffect.choices())
    condition = models.JSONField()
    priority = models.IntegerField(default=0)
    description = models.CharField(max_length=300, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)


class UserAttribute(models.Model):
    """A subject attribute (e.g. ``approval_limit``) keyed by user, supplied to ABAC (F14b)."""

    user_id = models.UUIDField(db_index=True)  # references users_user by value (I2)
    key = models.CharField(max_length=100)
    value = models.JSONField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_id", "key"], name="uniq_user_attribute")
        ]
