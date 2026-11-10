from enum import StrEnum


class PolicyEffect(StrEnum):
    """How a matching ABAC policy affects the decision (feeds the model field)."""

    ALLOW_IF = "allow_if"
    DENY_IF = "deny_if"

    @classmethod
    def choices(cls) -> list[tuple[str, str]]:
        """Pairs for a Django model field's ``choices=`` (value, human label)."""
        return [(e.value, e.name.title()) for e in cls]
