from __future__ import annotations

from django.db import connection
from django.http import HttpResponse, JsonResponse
from django_tenants.utils import get_public_schema_name

from easybiz.core.api import envelope
from easybiz.core.api.security import TenantJWTAuth
from easybiz.core.iam import service as iam
from easybiz.core.idempotency import service

_MAX_KEY = 200  # the idem_key.key column width

# Endpoints whose 2xx body carries a secret skip idempotency entirely — caching would leave the
# secret at rest in idem_key.body. (The op is not replay-safe to store here.)
_NO_CACHE_PATHS = frozenset({"/api/core/apikeys"})


class IdempotencyMiddleware:
    """Replay/guard keyed POSTs by an authenticated caller on the tenant plane; else passthrough."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = request.headers.get("Idempotency-Key")
        caller = self._caller(request) if key else ""
        if (
            request.method != "POST"
            or not key
            or len(key) > _MAX_KEY
            or not caller  # unauthenticated callers never engage idempotency (login stays uncached)
            or request.path in _NO_CACHE_PATHS  # secret-returning endpoints are never cached
            or connection.schema_name == get_public_schema_name()
        ):
            return self.get_response(request)

        path = request.get_full_path()
        req_hash = service.request_hash(request.method, path, request.body)
        rid = getattr(request, "request_id", None)
        claim = service.claim(caller, key, path, req_hash)

        if claim.kind == service.REPLAY:
            resp = HttpResponse(
                claim.body, status=claim.response_status, content_type="application/json"
            )
            resp["Idempotency-Replayed"] = "true"
            return resp
        if claim.kind == service.CONFLICT:
            body = envelope.build(
                "a request with this Idempotency-Key is already in progress",
                409,
                code="resource.conflict",
                request_id=rid,
            )
            return JsonResponse(body, status=409)
        if claim.kind == service.MISMATCH:
            body = envelope.build(
                "Idempotency-Key was already used with a different request",
                422,
                code="idempotency.payload_mismatch",
                request_id=rid,
            )
            return JsonResponse(body, status=422)

        try:
            response = self.get_response(request)
        except Exception:
            service.release(caller, key, req_hash)  # never strand the key on a handler crash
            raise
        try:
            stored = None if getattr(response, "streaming", False) else response.content.decode()
        except UnicodeDecodeError:
            stored = None  # a non-text 2xx body is not cacheable here
        if stored is None:
            service.release(caller, key, req_hash)
        else:
            service.finalize(caller, key, req_hash, response.status_code, stored)
        return response

    @staticmethod
    def _caller(request) -> str:
        """A stable principal id from the credential (like ToolPrincipalAuth); '' if unresolved."""
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            user = TenantJWTAuth._user_from_token(request, header[7:])
            return f"user:{user.id}" if user is not None else ""
        if header.startswith("ApiKey "):
            key = iam.authenticate_api_key(header[7:])
            return f"key:{key.id}" if key is not None else ""
        return ""
