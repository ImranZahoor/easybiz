from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from easybiz.core.idempotency.models import IdemKey

TTL = timedelta(hours=24)

FRESH = "fresh"  # we own the key — run the handler
REPLAY = "replay"  # a completed response is stored — return it
CONFLICT = "conflict"  # a duplicate is still in progress
MISMATCH = "mismatch"  # the key was used with a different request


@dataclass
class Claim:
    kind: str
    response_status: int | None = None
    body: str = ""


def request_hash(method: str, path: str, body: bytes, auth_header: str) -> str:
    """sha256 over method/path/credential/body — the credential blocks cross-caller replay."""
    h = hashlib.sha256()
    h.update(method.encode())
    h.update(b"\n")
    h.update(path.encode())
    h.update(b"\n")
    h.update(auth_header.encode())
    h.update(b"\n")
    h.update(body)
    return h.hexdigest()


def claim(key: str, endpoint: str, request_hash: str) -> Claim:
    """Own the key (insert), or decide replay/conflict/mismatch against the existing row."""
    now = timezone.now()
    with transaction.atomic():
        try:
            with transaction.atomic():  # savepoint: a losing insert must not abort the outer tx
                IdemKey.objects.create(
                    key=key,
                    endpoint=endpoint,
                    request_hash=request_hash,
                    status="in_progress",
                    expires_at=now + TTL,
                )
            return Claim(FRESH)
        except IntegrityError:
            pass
        row = IdemKey.objects.select_for_update().get(key=key)
        if row.expires_at <= now:  # stale — reclaim it for this request
            row.endpoint = endpoint
            row.request_hash = request_hash
            row.status = "in_progress"
            row.response_status = None
            row.body = ""
            row.expires_at = now + TTL
            row.save()
            return Claim(FRESH)
        if row.request_hash != request_hash:
            return Claim(MISMATCH)
        if row.status == "completed":
            return Claim(REPLAY, response_status=row.response_status, body=row.body)
        return Claim(CONFLICT)


def finalize(key: str, response_status: int, body: str) -> None:
    """Store a completed 2xx response; any other status releases the key for a retry."""
    rows = IdemKey.objects.filter(key=key, status="in_progress")
    if 200 <= response_status < 300:
        rows.update(status="completed", response_status=response_status, body=body)
    else:
        rows.delete()
