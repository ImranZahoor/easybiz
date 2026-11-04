from easybiz.core.kernel.registry import registry


def test_manifest_declares_permissions_roles_and_events():
    m = registry.manifest("timesheets")
    codes = {c for c, _ in m.permissions}
    assert codes == {
        "timesheets.project.read",
        "timesheets.project.manage",
        "timesheets.entry.create",
        "timesheets.entry.read",
        "timesheets.entry.approve",
    }
    assert set(m.publishes) == {"timesheets.entry.approved", "timesheets.entry.rejected"}
    role_names = {r["name"] for r in m.roles}
    assert {"timesheet_user", "timesheet_approver"} <= role_names
    assert [i["route"] for i in m.menu] == ["/timesheets", "/timesheets/projects"]
