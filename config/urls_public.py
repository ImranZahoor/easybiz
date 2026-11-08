from django.http import JsonResponse
from django.urls import path

from easybiz.core.platform_api import platform_api


def health(_request):
    """Liveness probe for the platform host."""
    return JsonResponse({"status": "ok", "scope": "platform"})


urlpatterns = [
    path("health", health),
    path("api/platform/", platform_api.urls),
]
