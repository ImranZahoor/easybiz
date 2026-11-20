from __future__ import annotations

from easybiz.core.api.security import TenantJWTAuth
from easybiz.core.iam import service as iam
from easybiz.core.tools.service import Principal


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
            return Principal.from_agent_key(key)
        return None


tool_principal = ToolPrincipalAuth()
