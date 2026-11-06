from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from ninja import Router
from ninja.errors import HttpError
from ninja.throttling import AnonRateThrottle

from easybiz.core.api.platform_security import encode_platform_token, platform_auth
from easybiz.core.platform_api.types import PlatformLoginIn, PlatformMeOut, PlatformTokenOut
from easybiz.core.users.models import User

router = Router()

# A real hash to verify against on the miss path, so a non-admin email costs the same
# time as a real one and cannot be enumerated by response latency.
_DUMMY_HASH = make_password("platform-login-timing-equalizer")


def _authenticate_platform(email: str, password: str) -> User | None:
    user = User.objects.filter(email=email.lower(), is_active=True, is_platform_admin=True).first()
    if user is None:
        check_password(password, _DUMMY_HASH)
        return None
    if not user.check_password(password):
        return None
    return user


@router.post(
    "/auth/login",
    auth=None,
    response=PlatformTokenOut,
    throttle=[AnonRateThrottle(settings.EASYBIZ_PLATFORM_LOGIN_RATE)],
)
def login(request, data: PlatformLoginIn):
    """Exchange platform-admin credentials for a platform token (throttled per IP)."""
    user = _authenticate_platform(data.email, data.password)
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
