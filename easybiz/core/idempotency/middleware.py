from __future__ import annotations

from django.db import connection
from django.http import HttpResponse, JsonResponse
from django_tenants.utils import get_public_schema_name

from easybiz.core.api import envelope
from easybiz.core.idempotency import service


class IdempotencyMiddleware:
    """Replay/guard keyed POSTs on the tenant plane; everything else passes through."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = request.headers.get("Idempotency-Key")
        if (
            request.method != "POST"
            or not key
            or connection.schema_name == get_public_schema_name()
        ):
            return self.get_response(request)

        path = request.get_full_path()
        req_hash = service.request_hash(
            request.method, path, request.body, request.headers.get("Authorization", "")
        )
        rid = getattr(request, "request_id", None)
        claim = service.claim(key, path, req_hash)

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

        response = self.get_response(request)
        stored = "" if getattr(response, "streaming", False) else response.content.decode()
        service.finalize(key, response.status_code, stored)
        return response
