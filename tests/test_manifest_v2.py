import pytest

from easybiz.core.kernel.manifest import ManifestError, parse_manifest


def test_v1_manifest_backward_compatible():
    m = parse_manifest(
        {
            "id": "demo",
            "name": "Demo",
            "version": "0.1.0",
            "provides": ["AttendanceProvider"],
            "consumes": ["Foo"],
        }
    )
    assert m.manifest_version == 1
    assert m.provides == [("AttendanceProvider", "1.0.0")]
    assert m.consumes == [("Foo", "*", False)]


def test_v2_provides_consumes_objects():
    m = parse_manifest(
        {
            "id": "hr",
            "name": "HR",
            "version": "1.0.0",
            "manifest_version": 2,
            "requires_core": "^1.0",
            "provides": [{"contract": "EmployeeProvider", "version": "1.2.0"}],
            "consumes": [{"contract": "AttendanceProvider", "range": "^1.0", "optional": True}],
            "extension_points": [
                {"name": "hr.leave_validator", "contract": "LeaveValidator", "version": "1.0.0"}
            ],
            "extends": [{"point": "demo.thing"}],
            "permissions": [{"code": "hr.pay.read", "description": "x", "sensitive": True}],
        }
    )
    assert m.manifest_version == 2 and m.requires_core == "^1.0"
    assert m.provides == [("EmployeeProvider", "1.2.0")]
    assert m.consumes == [("AttendanceProvider", "^1.0", True)]
    assert m.extension_points[0]["name"] == "hr.leave_validator"
    assert m.extends[0]["point"] == "demo.thing"
    assert m.sensitive_permissions == frozenset({"hr.pay.read"})


def test_v2_rejects_bare_string_provides():
    with pytest.raises(ManifestError):
        parse_manifest(
            {
                "id": "hr",
                "name": "HR",
                "version": "1.0.0",
                "manifest_version": 2,
                "provides": ["EmployeeProvider"],
            }
        )


def test_v2_rejects_bad_extension_point_and_bad_sensitive_and_bad_requires_core():
    base = {"id": "hr", "name": "HR", "version": "1.0.0", "manifest_version": 2}
    with pytest.raises(ManifestError):
        parse_manifest({**base, "extension_points": [{"contract": "X"}]})  # missing name
    with pytest.raises(ManifestError):
        parse_manifest({**base, "permissions": [{"code": "hr.x", "sensitive": "yes"}]})  # non-bool
    with pytest.raises(ManifestError):
        parse_manifest({**base, "requires_core": "not-a-range"})


def test_v2_accepts_and_ignores_forward_declared_keys():
    # keys for unbuilt features (F5-F18) must not break loading; they are simply not surfaced yet
    m = parse_manifest(
        {
            "id": "hr",
            "name": "HR",
            "version": "1.0.0",
            "manifest_version": 2,
            "settings": [{"key": "x"}],
            "jobs": [],
            "ui": {"menu": []},
        }
    )
    assert m.manifest_version == 2  # parsed fine, forward-declared keys ignored
