from django_tenants.utils import tenant_context

from easybiz.core.events.models import OutboxEvent
from tests.test_timesheets_entries_api import _add_user, _project, _setup
from tests.test_timesheets_projects_api import _post


def _submitted_entry(pid, slug, author_tok):
    eid = _post(
        "/api/timesheets/entries",
        author_tok,
        {"project_id": pid, "work_date": "2026-11-03", "hours": "8.0"},
        slug=slug,
    ).json()["id"]
    _post(f"/api/timesheets/entries/{eid}/submit", author_tok, {}, slug=slug)
    return eid


def test_approve_sets_approved_and_publishes_event(synced, provision):
    tenant, owner = _setup(provision, "tsr1")
    pid = _project(owner, "tsr1")
    _, author = _add_user(tenant, "a@tsr1.test", ["timesheet_user"])
    _, appr = _add_user(tenant, "app@tsr1.test", ["timesheet_approver"])
    eid = _submitted_entry(pid, "tsr1", author)

    r = _post(f"/api/timesheets/entries/{eid}/approve", appr, {}, slug="tsr1")
    assert r.status_code == 200 and r.json()["status"] == "approved"
    with tenant_context(tenant):
        ev = OutboxEvent.objects.filter(name="timesheets.entry.approved").first()
        assert ev is not None
        assert ev.payload["entry_id"] == eid and ev.payload["hours"] == "8.00"
        assert set(ev.payload) == {"entry_id", "user_id", "project_id", "work_date", "hours"}


def test_cannot_approve_non_submitted(synced, provision):
    tenant, owner = _setup(provision, "tsr2")
    pid = _project(owner, "tsr2")
    _, author = _add_user(tenant, "a@tsr2.test", ["timesheet_user"])
    _, appr = _add_user(tenant, "app@tsr2.test", ["timesheet_approver"])
    eid = _post(
        "/api/timesheets/entries",
        author,
        {"project_id": pid, "work_date": "2026-11-03", "hours": "8.0"},
        slug="tsr2",
    ).json()["id"]  # still draft
    assert _post(f"/api/timesheets/entries/{eid}/approve", appr, {}, slug="tsr2").status_code == 409


def test_cannot_review_own_time(synced, provision):
    tenant, owner = _setup(provision, "tsr3")
    pid = _project(owner, "tsr3")
    _, appr = _add_user(tenant, "app@tsr3.test", ["timesheet_approver"])
    eid = _submitted_entry(pid, "tsr3", appr)  # approver submits their own time
    assert _post(f"/api/timesheets/entries/{eid}/approve", appr, {}, slug="tsr3").status_code == 403


def test_approve_requires_permission(synced, provision):
    tenant, owner = _setup(provision, "tsr4")
    pid = _project(owner, "tsr4")
    _, author = _add_user(tenant, "a@tsr4.test", ["timesheet_user"])
    _, other = _add_user(tenant, "o@tsr4.test", ["timesheet_user"])
    eid = _submitted_entry(pid, "tsr4", author)
    assert (
        _post(f"/api/timesheets/entries/{eid}/approve", other, {}, slug="tsr4").status_code == 403
    )


def test_reject_sets_rejected_and_publishes_event(synced, provision):
    tenant, owner = _setup(provision, "tsr5")
    pid = _project(owner, "tsr5")
    _, author = _add_user(tenant, "a@tsr5.test", ["timesheet_user"])
    _, appr = _add_user(tenant, "app@tsr5.test", ["timesheet_approver"])
    eid = _submitted_entry(pid, "tsr5", author)

    r = _post(
        f"/api/timesheets/entries/{eid}/reject", appr, {"reason": "too many hours"}, slug="tsr5"
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    with tenant_context(tenant):
        assert OutboxEvent.objects.filter(name="timesheets.entry.rejected").exists()


def test_double_approve_409(synced, provision):
    tenant, owner = _setup(provision, "tsr6")
    pid = _project(owner, "tsr6")
    _, author = _add_user(tenant, "a@tsr6.test", ["timesheet_user"])
    _, appr = _add_user(tenant, "app@tsr6.test", ["timesheet_approver"])
    eid = _submitted_entry(pid, "tsr6", author)
    assert _post(f"/api/timesheets/entries/{eid}/approve", appr, {}, slug="tsr6").status_code == 200
    assert _post(f"/api/timesheets/entries/{eid}/approve", appr, {}, slug="tsr6").status_code == 409
