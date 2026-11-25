from ninja import Schema


class PageIn(Schema):
    """Shared pagination + field-limiting input for list tools."""

    limit: int = 50
    cursor: str | None = None
    fields: list[str] | None = None  # project each item to these keys (None = full item)


def project(items: list[dict], fields: list[str] | None) -> list[dict]:
    """Trim each item dict to the requested keys (intersection; unknown keys absent)."""
    if not fields:
        return items
    keep = set(fields)
    return [{k: v for k, v in item.items() if k in keep} for item in items]
