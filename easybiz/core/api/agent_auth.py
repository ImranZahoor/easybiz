from __future__ import annotations

from easybiz.core.api.security import TenantJWTAuth
from easybiz.core.iam import service as iam
from easybiz.core.tools.service import Principal
from easybiz.core.users.models import Membership, User


class ToolPrincipalAuth:
    """Resolve a tenant JWT user OR a scoped agent key to a tool Principal (else 401)."""

    def __call__(self, request):
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            user = TenantJWTAuth._user_from_token(request, header[7:])
            return Principal.from_user(user.id) if user is not None else None
        if header.startswith("ApiKey "):
            key = iam.authenticate_api_key(header[7:])
            # a plain service key (no on-behalf user) is not usable on the tool transport
            if key is None or key.on_behalf_of_user is None:
                return None
            # the on-behalf user must still be an active member (parity with the JWT path),
            # so a suspended/removed user's keys stop working even if role rows linger
            if not _active_member(key.on_behalf_of_user, request.tenant):
                return None
            return Principal.from_agent_key(key)
        return None


def _active_member(user_id, tenant) -> bool:
    if not User.objects.filter(id=user_id, is_active=True).exists():
        return False
    return Membership.objects.filter(user_id=user_id, tenant=tenant, is_active=True).exists()


tool_principal = ToolPrincipalAuth()
