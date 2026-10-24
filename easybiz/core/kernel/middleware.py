"""Request gates: suspended-tenant block and per-tenant module routing."""

from __future__ import annotations

import re

from django.http import JsonResponse

_MODULE_PATH = re.compile(r"^/api/([a-z][a-z0-9_]*)/")


class TenantStatusMiddleware:
    """403 for every path when the resolved tenant is suspended."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        tenant = getattr(request, "tenant", None)
        if tenant is not None and tenant.is_active is False:
            return JsonResponse({"detail": "This tenant is suspended"}, status=403)
        return self.get_response(request)


class ModuleGateMiddleware:
    """404 for routes of an installed module the tenant has not enabled."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        match = _MODULE_PATH.match(request.path)
        if match:
            from easybiz.core.kernel import state
            from easybiz.core.kernel.registry import registry

            segment = match.group(1)
            tenant = getattr(request, "tenant", None)
            if (
                registry.manifest(segment) is not None
                and tenant is not None
                and not state.is_enabled(tenant, segment)
            ):
                return JsonResponse(
                    {"detail": f"Module '{segment}' is not enabled for this tenant"},
                    status=404,
                )
        return self.get_response(request)
