from enum import StrEnum


class EntryStatus(StrEnum):
    """Lifecycle states of a time entry (domain vocabulary; feeds the model field and DTOs)."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Pairs for a Django model field's ``choices=`` (value, human label)."""
        return [(s.value, s.name.title()) for s in cls]
