from __future__ import annotations

from easybiz.core.users.models import Membership, User


class WeakPassword(Exception):
    """A new account was requested without a valid (≥10-char) password (HTTP 422)."""


def authenticate(email: str, password: str, tenant) -> User | None:
    """Return the user for valid credentials with an active membership of ``tenant``, else None."""
    user = User.objects.filter(email=email.lower(), is_active=True).first()
    if user is None or not user.check_password(password):
        return None
    if not Membership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
        return None
    return user


def create_user(email: str, tenant, password: str | None = None, name: str = "") -> User:
    """Reuse an existing user, or create one (new accounts need a ≥10-char password);
    then ensure an active membership of ``tenant``."""
    user = User.objects.filter(email=email.lower()).first()
    if user is None:
        if not password or len(password) < 10:
            raise WeakPassword("a new account needs a password of at least 10 characters")
        user = User.objects.create_user(email=email, password=password, name=name)
    Membership.objects.get_or_create(user=user, tenant=tenant, defaults={"is_active": True})
    return user
