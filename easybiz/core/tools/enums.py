from enum import StrEnum


class ToolTier(StrEnum):
    """A tool's risk tier, derived mechanically from command-vs-query (feeds exposure rules)."""

    READ = "read"
    WRITE = "write"
    ADMIN = "admin"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        return [(t.value, t.name.title()) for t in cls]
