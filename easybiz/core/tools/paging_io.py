from ninja import Schema


class PageIn(Schema):
    """Shared pagination input for list tools (keyset cursor paging)."""

    limit: int = 50
    cursor: str | None = None
