from __future__ import annotations

import time

import jwt
from django.conf import settings
from django_tenants.utils import get_public_schema_name
from ninja.errors import HttpError
from ninja.security import HttpBearer

from easybiz.core.iam import cache as iam_cache
from easybiz.core.iam import service as iam
from easybiz.core.users.models import Membership, User


def encode_tenant_token(user_id, schema_name: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "tenant": schema_name,
        "iat": now,
        "exp": now + settings.EASYBIZ_JWT_TTL_SECONDS,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])


class TenantJWTAuth(HttpBearer):
    """Validate a tenant token (I9) and, when given, an endpoint permission."""

    def __init__(self, permission: str | None = None) -> None:
        self.permission = permission
        super().__init__()

    def authenticate(self, request, token):
        user = self._user_from_token(request, token)
        if user is None:
            return None
        if self.permission is not None and not self._grants(user, self.permission):
            raise HttpError(403, f"Missing permission {self.permission}")
        return user

    @staticmethod
    def _user_from_token(request, token) -> User | None:
        """Resolve the active user bound to this token for the host tenant, else None."""
        tenant = getattr(request, "tenant", None)
        if tenant is None or tenant.schema_name == get_public_schema_name():
            return None
        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            return None
        if payload.get("tenant") != tenant.schema_name:
            return None
        sub = payload.get("sub")
        if sub is None:
            return None
        user = User.objects.filter(id=sub, is_active=True).first()
        if user is None:
            return None
        is_member = Membership.objects.filter(user=user, tenant=tenant, is_active=True).exists()
        return user if is_member else None

    @staticmethod
    def _grants(user, permission: str) -> bool:
        return iam.has_permission(iam_cache.cached_permissions_for(user.id), permission)


def perm(code: str) -> TenantJWTAuth:
    return TenantJWTAuth(permission=code)


authenticated = TenantJWTAuth()
