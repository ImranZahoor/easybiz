"""Tenant JWT auth, the ``perm()`` guard, and the /auth endpoints."""

from __future__ import annotations

import time

import jwt
from django.conf import settings
from django_tenants.utils import get_public_schema_name
from ninja import Router
from ninja.errors import HttpError
from ninja.security import HttpBearer

from easybiz.core.api.types import LoginIn, MeOut, TokenOut
from easybiz.core.iam import service as iam
from easybiz.core.kernel import state
from easybiz.core.users import service as users
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
        tenant = getattr(request, "tenant", None)
        if tenant is None or tenant.schema_name == get_public_schema_name():
            return None
        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            return None
        if payload.get("tenant") != tenant.schema_name:
            return None
        user = User.objects.filter(id=payload.get("sub"), is_active=True).first()
        if user is None:
            return None
        if not Membership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
            return None
        if self.permission is not None:
            perms = iam.permissions_for(user.id)
            if not iam.has_permission(perms, self.permission):
                raise HttpError(403, f"Missing permission {self.permission}")
        return user


def perm(code: str) -> TenantJWTAuth:
    return TenantJWTAuth(permission=code)


authenticated = TenantJWTAuth()

router = Router()


@router.post("/login", auth=None, response=TokenOut)
def login(request, data: LoginIn):
    """Exchange tenant credentials for a tenant access token."""
    user = users.authenticate(data.email, data.password, request.tenant)
    if user is None:
        raise HttpError(401, "Invalid credentials")
    return TokenOut(
        access_token=encode_tenant_token(user.id, request.tenant.schema_name),
        expires_in=settings.EASYBIZ_JWT_TTL_SECONDS,
    )


@router.get("/me", auth=authenticated, response=MeOut)
def me(request):
    """The caller's identity, effective permissions, enabled modules, and menu."""
    user = request.auth
    perms = iam.permissions_for(user.id)
    return MeOut(
        id=str(user.id),
        email=user.email,
        permissions=sorted(perms),
        enabled_modules=sorted(state.enabled_module_ids(request.tenant)),
        menu=iam.menu_for(request.tenant, perms),
    )
