from ninja import NinjaAPI
from ninja.errors import AuthenticationError, ValidationError

from easybiz.core.api import envelope
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


def _envelope(request, detail, status, *, code=None, errors=None):
    body = envelope.build(
        detail, status, code=code, request_id=getattr(request, "request_id", None), errors=errors
    )
    return platform_api.create_response(request, body, status=status)


@platform_api.exception_handler(TenantConflict)
def _on_conflict(request, exc):
    return _envelope(request, str(exc), 409)


@platform_api.exception_handler(LifecycleError)
def _on_lifecycle_error(request, exc):
    return _envelope(request, str(exc), 409)


@platform_api.exception_handler(TenantValidationError)
def _on_validation(request, exc):
    return _envelope(request, str(exc), 422)


@platform_api.exception_handler(WeakPassword)
def _on_weak_password(request, exc):
    return _envelope(request, str(exc), 422)


@platform_api.exception_handler(DomainError)
def _on_domain_error(request, exc: DomainError):
    return _envelope(request, str(exc), exc.status, code=exc.code)


@platform_api.exception_handler(ValidationError)
def _on_ninja_validation(request, exc: ValidationError):
    return _envelope(request, "validation failed", 422, errors=envelope.field_errors(exc))


@platform_api.exception_handler(AuthenticationError)
def _on_auth_error(request, exc: AuthenticationError):
    return _envelope(request, "authentication required", 401)
