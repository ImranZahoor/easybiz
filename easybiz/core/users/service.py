"""Authentication against the global user directory + per-tenant membership."""

from __future__ import annotations

from easybiz.core.users.models import Membership, User


def authenticate(email: str, password: str, tenant) -> User | None:
    """Return the user for valid credentials with an active membership of ``tenant``, else None."""
    user = User.objects.filter(email=email.lower(), is_active=True).first()
    if user is None or not user.check_password(password):
        return None
    if not Membership.objects.filter(user=user, tenant=tenant, is_active=True).exists():
        return None
    return user
