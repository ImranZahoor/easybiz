class DomainError(Exception):
    """A domain-rule violation carrying the HTTP status the API should return.

    Subsystems and modules raise a subclass (or this directly); the tenant API
    maps every DomainError to its status in one place (no per-handler try/except).
    """

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.status = status
