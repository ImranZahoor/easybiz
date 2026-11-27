import importlib
import importlib.util

from ninja import NinjaAPI
from ninja.errors import AuthenticationError, HttpError, ValidationError

from easybiz.core.api import envelope
from easybiz.core.api.auth import router as auth_router
from easybiz.core.api.core_routes import router as core_router
from easybiz.core.api.mcp_routes import router as mcp_router
from easybiz.core.api.tools_routes import router as tools_router
from easybiz.core.errors import DomainError
from easybiz.core.kernel.registry import registry

api = NinjaAPI(urls_namespace="easybiz", title="Easybiz Tenant API")
api.add_router("/auth", auth_router)
api.add_router("/core", core_router)
api.add_router("/tools", tools_router)
api.add_router("/mcp", mcp_router)


def _envelope(request, detail, status, *, code=None, errors=None):
    body = envelope.build(
        detail, status, code=code, request_id=getattr(request, "request_id", None), errors=errors
    )
    return api.create_response(request, body, status=status)


@api.exception_handler(DomainError)
def _on_domain_error(request, exc: DomainError):
    """Map any domain error to its HTTP status, so handlers need no try/except."""
    return _envelope(request, str(exc), exc.status, code=exc.code)


@api.exception_handler(HttpError)
def _on_http_error(request, exc: HttpError):
    """ninja's HttpError (perm guard, login, write routes) through the same envelope."""
    return _envelope(request, exc.message, exc.status_code)


@api.exception_handler(ValidationError)
def _on_validation_error(request, exc: ValidationError):
    return _envelope(request, "validation failed", 422, errors=envelope.field_errors(exc))


@api.exception_handler(AuthenticationError)
def _on_auth_error(request, exc: AuthenticationError):
    return _envelope(request, "authentication required", 401)


def _mount_module_routers() -> None:
    """Mount each installed module's API router at /<id>; per-tenant gating is middleware's job."""
    for module_id in registry.module_ids():
        dotted = f"easybiz.modules.{module_id}.api"
        if importlib.util.find_spec(dotted) is None:
            continue
        module = importlib.import_module(dotted)
        router = getattr(module, "router", None)
        if router is not None:
            api.add_router(f"/{module_id}", router)


_mount_module_routers()
