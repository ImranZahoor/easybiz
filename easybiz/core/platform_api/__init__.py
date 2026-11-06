from ninja import NinjaAPI

from easybiz.core.errors import DomainError
from easybiz.core.kernel.lifecycle import LifecycleError
from easybiz.core.kernel.tenants import TenantConflict, TenantValidationError
from easybiz.core.platform_api.admins import router as admins_router
from easybiz.core.platform_api.auth import router as auth_router
from easybiz.core.platform_api.modules import router as modules_router
from easybiz.core.platform_api.tenants import router as tenants_router
from easybiz.core.users.service import WeakPassword

platform_api = NinjaAPI(urls_namespace="platform_api", title="Easybiz Platform API")
platform_api.add_router("", auth_router)
platform_api.add_router("", tenants_router)
platform_api.add_router("", modules_router)
platform_api.add_router("", admins_router)


@platform_api.exception_handler(TenantConflict)
def _on_conflict(request, exc):
    return platform_api.create_response(request, {"detail": str(exc)}, status=409)


@platform_api.exception_handler(LifecycleError)
def _on_lifecycle_error(request, exc):
    return platform_api.create_response(request, {"detail": str(exc)}, status=409)


@platform_api.exception_handler(TenantValidationError)
def _on_validation(request, exc):
    return platform_api.create_response(request, {"detail": str(exc)}, status=422)


@platform_api.exception_handler(WeakPassword)
def _on_weak_password(request, exc):
    return platform_api.create_response(request, {"detail": str(exc)}, status=422)


@platform_api.exception_handler(DomainError)
def _on_domain_error(request, exc: DomainError):
    return platform_api.create_response(request, {"detail": str(exc)}, status=exc.status)
