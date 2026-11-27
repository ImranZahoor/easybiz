from __future__ import annotations

# Appendix E codes keyed by HTTP status, used when a raise site gives no explicit code.
DEFAULT_CODES: dict[int, str] = {
    401: "auth.token_invalid",
    403: "auth.forbidden",
    404: "resource.not_found",
    409: "resource.conflict",
    412: "resource.version_mismatch",
    422: "validation.failed",
    428: "resource.precondition_required",
    429: "rate.limited",
}


def build(
    detail: str,
    status: int,
    *,
    code: str | None = None,
    request_id: str | None = None,
    errors: list | None = None,
) -> dict:
    """The error envelope: detail (human) + stable code + field errors + request id."""
    return {
        "detail": detail,
        "code": code or DEFAULT_CODES.get(status, "error"),
        "errors": errors or [],
        "request_id": request_id,
    }


def field_errors(exc) -> list[dict]:
    """Flatten a ninja ValidationError into [{field, code, message}]."""
    return [
        {
            "field": str(e["loc"][-1]) if e.get("loc") else "",
            "code": e.get("type", "invalid"),
            "message": e.get("msg", ""),
        }
        for e in exc.errors
    ]
