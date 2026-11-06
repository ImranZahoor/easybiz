from __future__ import annotations

from django.conf import settings
from ninja import Router
from ninja.errors import HttpError

from easybiz.core.api.security import authenticated, encode_tenant_token
from easybiz.core.api.types import LoginIn, MeOut, TokenOut
from easybiz.core.iam import service as iam
from easybiz.core.users import service as users

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
    """The caller's identity, effective permissions, and menu."""
    user = request.auth
    perms = iam.permissions_for(user.id)
    return MeOut(
        id=str(user.id),
        email=user.email,
        permissions=sorted(perms),
        menu=iam.menu_for(request.tenant, perms),
    )
