from tests.test_timesheets_entries_api import _add_user, _project, _setup
from tests.test_timesheets_projects_api import _post


def test_malformed_project_id_is_422_not_500(synced, provision):
    tenant, owner = _setup(provision, "tsv1")
    _, tok = _add_user(tenant, "u@tsv1.test", ["timesheet_user"])
    r = _post(
        "/api/timesheets/entries",
        tok,
        {"project_id": "not-a-uuid", "work_date": "2026-11-03", "hours": "8.0"},
        slug="tsv1",
    )
    assert r.status_code == 422


def test_malformed_entry_id_is_422_not_500(synced, provision):
    tenant, owner = _setup(provision, "tsv2")
    _, tok = _add_user(tenant, "u@tsv2.test", ["timesheet_user"])
    assert (
        _post("/api/timesheets/entries/not-a-uuid/submit", tok, {}, slug="tsv2").status_code == 422
    )


def test_sub_centihour_and_extra_precision_are_422(synced, provision):
    tenant, owner = _setup(provision, "tsv3")
    pid = _project(owner, "tsv3")
    _, tok = _add_user(tenant, "u@tsv3.test", ["timesheet_user"])
    for bad in ("0.004", "7.333"):
        r = _post(
            "/api/timesheets/entries",
            tok,
            {"project_id": pid, "work_date": "2026-11-03", "hours": bad},
            slug="tsv3",
        )
        assert r.status_code == 422, bad
