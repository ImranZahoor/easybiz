from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.audit.models import AuditLog
from easybiz.core.events.models import OutboxEvent
from tests.test_timesheets_entries_api import _add_user, _project, _setup
from tests.test_timesheets_projects_api import _post

# The generic event-engine properties the spec lists under this file — undeclared-publish
# rejection, inbox idempotency, parked-then-replayed, retry-then-dead — are proven against the
# `demo` module in tests/test_events_*.py (M5); they exercise the same engine code path and are
# not re-skinned here. This file proves the Timesheets-specific flow and wiring.


def _me(token, slug):
    return (
        Client()
        .get("/api/auth/me", HTTP_HOST=f"{slug}.localhost", HTTP_AUTHORIZATION=f"Bearer {token}")
        .json()
    )


def test_full_submit_approve_flow(synced, provision):
    tenant, owner = _setup(provision, "tsflow")
    pid = _project(owner, "tsflow")
    _, author = _add_user(tenant, "author@tsflow.test", ["timesheet_user"])
    _, approver = _add_user(tenant, "approver@tsflow.test", ["timesheet_approver"])

    eid = _post(
        "/api/timesheets/entries",
        author,
        {"project_id": pid, "work_date": "2026-11-03", "hours": "7.50"},
        slug="tsflow",
    ).json()["id"]
    assert (
        _post(f"/api/timesheets/entries/{eid}/submit", author, {}, slug="tsflow").json()["status"]
        == "submitted"
    )
    approved = _post(f"/api/timesheets/entries/{eid}/approve", approver, {}, slug="tsflow")
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    with tenant_context(tenant):
        assert AuditLog.objects.filter(action="timesheets.entry.approved", entity_id=eid).exists()
        ev = OutboxEvent.objects.filter(name="timesheets.entry.approved").first()
        assert ev is not None and ev.payload["entry_id"] == eid and ev.payload["hours"] == "7.50"


def test_menu_follows_permissions(synced, provision):
    tenant, _ = _setup(provision, "tsmenu")
    _, author = _add_user(tenant, "author@tsmenu.test", ["timesheet_user"])
    _, approver = _add_user(tenant, "approver@tsmenu.test", ["timesheet_approver"])

    author_labels = {i["label"] for i in _me(author, "tsmenu")["menu"]}
    approver_labels = {i["label"] for i in _me(approver, "tsmenu")["menu"]}
    assert "Timesheets" in author_labels and "Projects" not in author_labels
    assert {"Timesheets", "Projects"} <= approver_labels
