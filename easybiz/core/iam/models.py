import uuid

from django.db import models


class Role(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(max_length=300, blank=True)
    is_system = models.BooleanField(default=False)
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
