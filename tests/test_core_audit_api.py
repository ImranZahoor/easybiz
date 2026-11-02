from django.test import Client

from tests.test_core_modules_api import _token


def test_audit_lists_actions(synced, provision):
    token = _token(provision)
    Client().post(
        "/api/core/modules/demo/enable",
        HTTP_HOST="acme.localhost",
        HTTP_AUTHORIZATION=f"Bearer {token}",
    )
    rows = (
        Client()
        .get("/api/core/audit", HTTP_HOST="acme.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")
        .json()
    )
    actions = {r["action"] for r in rows}
    assert {"tenant.provisioned", "module.enabled"} <= actions
