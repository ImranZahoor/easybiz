from __future__ import annotations

import time

import jwt
from django.conf import settings
from django_tenants.utils import get_public_schema_name
from ninja.security import HttpBearer

from easybiz.core.api.security import decode_token
from easybiz.core.users.models import User


def encode_platform_token(user_id) -> str:
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "scope": "platform",
        "iat": now,
        "exp": now + settings.EASYBIZ_PLATFORM_JWT_TTL_SECONDS,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm="HS256")


class PlatformJWTAuth(HttpBearer):
    """Validate a platform token: public host only, scope=platform, live admin check."""

    def authenticate(self, request, token) -> User | None:
        tenant = getattr(request, "tenant", None)
        if tenant is None or tenant.schema_name != get_public_schema_name():
            return None
        try:
            payload = decode_token(token)
        except jwt.PyJWTError:
            return None
        if payload.get("scope") != "platform":
            return None
        sub = payload.get("sub")
        if sub is None:
            return None
        # Read is_platform_admin live so a demotion takes effect on the next request.
        return User.objects.filter(id=sub, is_active=True, is_platform_admin=True).first()


platform_auth = PlatformJWTAuth()
