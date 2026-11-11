import pytest

from easybiz.core.kernel.manifest import parse_manifest
from easybiz.core.kernel.registry import Registry, RegistryError

V2 = {"manifest_version": 2, "version": "1.0.0"}
POINT = {"name": "demo.p", "contract": "AttendanceProvider", "version": "1.0.0"}


def _reg(*manifests):
    r = Registry()
    for d in manifests:
        r.add(parse_manifest(d, package=f"pkg.{d['id']}"))
    return r


def test_extension_point_unknown_contract_rejected():
    r = _reg(
        {
            **V2,
            "id": "demo",
            "name": "D",
            "extension_points": [{"name": "demo.p", "contract": "Nope"}],
        }
    )
    with pytest.raises(RegistryError):
        r.load_order()


def test_extends_unknown_point_rejected():
    r = _reg({**V2, "id": "hr", "name": "HR", "extends": [{"point": "demo.p"}]})
    with pytest.raises(RegistryError):
        r.load_order()


def test_extends_requires_host():
    host = {**V2, "id": "demo", "name": "D", "extension_points": [POINT]}
    ext = {
        **V2,
        "id": "hr",
        "name": "HR",
        "extends": [{"point": "demo.p"}],
    }  # does not require demo
    with pytest.raises(RegistryError):
        _reg(host, ext).load_order()


def test_extends_valid_when_host_required():
    host = {**V2, "id": "demo", "name": "D", "extension_points": [POINT]}
    ext = {
        **V2,
        "id": "hr",
        "name": "HR",
        "requires": [{"module": "demo"}],
        "extends": [{"point": "demo.p"}],
    }
    _reg(host, ext).load_order()  # no raise


def test_extends_version_mismatch_rejected():
    host = {**V2, "id": "demo", "name": "D", "extension_points": [POINT]}  # version 1.0.0
    ext = {
        **V2,
        "id": "hr",
        "name": "HR",
        "requires": [{"module": "demo"}],
        "extends": [{"point": "demo.p", "range": ">=2.0"}],
    }
    with pytest.raises(RegistryError):
        _reg(host, ext).load_order()


def test_duplicate_point_name_rejected():
    a = {**V2, "id": "demo", "name": "D", "extension_points": [POINT]}
    b = {**V2, "id": "timesheets", "name": "T", "extension_points": [POINT]}
    with pytest.raises(RegistryError):
        _reg(a, b).load_order()
