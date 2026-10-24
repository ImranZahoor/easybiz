from ninja import NinjaAPI

from easybiz.core.api.auth import router as auth_router

api = NinjaAPI(urls_namespace="easybiz", title="Easybiz Tenant API")
api.add_router("/auth", auth_router)
