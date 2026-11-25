from __future__ import annotations

import base64
import json
from datetime import date

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q

from easybiz.core.errors import DomainError

MAX_LIMIT = 200


class CursorError(DomainError):
    """A malformed or tampered pagination cursor (maps to HTTP 422)."""

    def __init__(self, message: str = "invalid cursor") -> None:
        super().__init__(message, 422)


def _encode(value, pk) -> str:
    raw = value.isoformat() if isinstance(value, date) else str(value)
    return base64.urlsafe_b64encode(json.dumps([raw, str(pk)]).encode()).decode()


def _decode(cursor: str) -> tuple[str, str]:
    try:
        value, pk = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        return value, pk
    except (ValueError, TypeError) as exc:
        raise CursorError() from exc


def paginate(
    queryset, *, limit: int = 50, cursor: str | None = None, order_by: str = "-id"
) -> dict:
    """Keyset-paginate a queryset over (order_by field, pk). Returns {items, next_cursor}."""
    limit = max(1, min(limit, MAX_LIMIT))
    field = order_by.lstrip("-")
    desc = order_by.startswith("-")
    tiebreak = "-pk" if desc else "pk"
    qs = queryset.order_by(order_by, tiebreak)
    if cursor:
        value, pk = _decode(cursor)
        op = "lt" if desc else "gt"
        try:
            # a bad/cross-tool cursor value raises here (filter build or query exec) → clean 422
            qs = qs.filter(Q(**{f"{field}__{op}": value}) | Q(**{field: value, f"pk__{op}": pk}))
            rows = list(qs[: limit + 1])
        except (DjangoValidationError, ValueError, TypeError) as exc:
            raise CursorError() from exc
    else:
        rows = list(qs[: limit + 1])
    if len(rows) > limit:
        last = rows[limit - 1]
        return {"items": rows[:limit], "next_cursor": _encode(getattr(last, field), last.pk)}
    return {"items": rows, "next_cursor": None}
