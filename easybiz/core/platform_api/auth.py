from django.conf import settings
from ninja import Router
from ninja.errors import HttpError
from ninja.throttling import AnonRateThrottle

from easybiz.core.api.platform_security import encode_platform_token, platform_auth
from easybiz.core.platform_api import queries
from easybiz.core.platform_api.types import PlatformLoginIn, PlatformMeOut, PlatformTokenOut

router = Router()


@router.post(
    "/auth/login",
    auth=None,
    response=PlatformTokenOut,
    throttle=[AnonRateThrottle(settings.EASYBIZ_PLATFORM_LOGIN_RATE)],
)
def login(request, data: PlatformLoginIn):
    """Exchange platform-admin credentials for a platform token (throttled per IP)."""
    user = queries.authenticate_platform(data.email, data.password)
    if user is None:
        raise HttpError(401, "Invalid credentials")
    return PlatformTokenOut(
        access_token=encode_platform_token(user.id),
        expires_in=settings.EASYBIZ_PLATFORM_JWT_TTL_SECONDS,
    )


@router.get("/me", auth=platform_auth, response=PlatformMeOut)
def me(request):
    """The platform admin's identity."""
    return PlatformMeOut(id=str(request.auth.id), email=request.auth.email)
