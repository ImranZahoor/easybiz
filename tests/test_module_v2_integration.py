from easybiz.core.kernel.registry import registry


def test_real_modules_load_with_v2_timesheets(synced):
    registry.ensure_loaded()
    registry.import_module_code()
    registry._assert_provides_registered()  # timesheets provides AttendanceProvider, registered
    ts = registry.manifest("timesheets")
    assert ts.manifest_version == 2 and ("AttendanceProvider", "1.0.0") in ts.provides
    assert registry.manifest("demo").manifest_version == 1  # demo still v1
