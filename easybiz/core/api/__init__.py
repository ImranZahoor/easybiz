import importlib
import importlib.util

from ninja import NinjaAPI

from easybiz.core.api.auth import router as auth_router
from easybiz.core.api.core_routes import router as core_router
from easybiz.core.kernel.registry import registry

api = NinjaAPI(urls_namespace="easybiz", title="Easybiz Tenant API")
api.add_router("/auth", auth_router)
api.add_router("/core", core_router)


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
