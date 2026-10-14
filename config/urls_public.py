"""Platform host URLs: health now; platform API mounts in M7."""
from django.http import JsonResponse
from django.urls import path


def health(_request):
    """Liveness probe for the platform host."""
    return JsonResponse({"status": "ok", "scope": "platform"})


urlpatterns = [
    path("health", health),
]
