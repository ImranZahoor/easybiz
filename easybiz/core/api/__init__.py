from ninja import NinjaAPI

from easybiz.core.api.auth import router as auth_router
from easybiz.core.api.core_routes import router as core_router

api = NinjaAPI(urls_namespace="easybiz", title="Easybiz Tenant API")
api.add_router("/auth", auth_router)
api.add_router("/core", core_router)
