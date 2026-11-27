from __future__ import annotations

import re
from uuid import uuid4

_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


class RequestIDMiddleware:
    """Stamp request.request_id (incoming X-Request-ID or a fresh id) and return it as a header."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = self._clean(request.headers.get("X-Request-ID")) or uuid4().hex
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        return response

    @staticmethod
    def _clean(raw) -> str | None:
        # accept a client id only if it is short and plain — never reflect hostile input into
        # a response header / log line (CRLF injection, log forging); else mint a fresh one
        if isinstance(raw, str) and _VALID_ID.match(raw):
            return raw
        return None
