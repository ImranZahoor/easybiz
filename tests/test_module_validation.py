import pytest

from easybiz.core.kernel.manifest import parse_manifest
from easybiz.core.kernel.registry import Registry, RegistryError

V2 = {"manifest_version": 2, "version": "1.0.0"}


def _reg(*manifests):
    r = Registry()
    for data in manifests:
        r.add(parse_manifest(data, package=f"pkg.{data['id']}"))
    return r


def test_provides_unknown_contract_rejected():
    r = _reg({**V2, "id": "hr", "name": "HR", "provides": [{"contract": "Nope"}]})
    with pytest.raises(RegistryError):
        r.load_order()


def test_consumes_unknown_contract_rejected():
    r = _reg({**V2, "id": "hr", "name": "HR", "consumes": [{"contract": "Nope", "optional": True}]})
    with pytest.raises(RegistryError):
        r.load_order()


def test_non_optional_unsatisfiable_consume_rejected():
    r = _reg({**V2, "id": "hr", "name": "HR", "consumes": [{"contract": "AttendanceProvider"}]})
    with pytest.raises(RegistryError):
        r.load_order()


def test_optional_unsatisfiable_consume_ok():
    r = _reg(
        {**V2, "id": "hr", "name": "HR", "consumes": [{"contract": "AttendanceProvider", "optional": True}]}
    )
    r.load_order()  # no raise


def test_requires_core_incompatible_rejected():
    r = _reg({**V2, "id": "hr", "name": "HR", "requires_core": ">=99.0"})
    with pytest.raises(RegistryError):
        r.load_order()


def test_provides_not_registered_rejected():
    r = _reg(
        {**V2, "id": "hr", "name": "HR", "provides": [{"contract": "AttendanceProvider", "version": "1.0.0"}]}
    )
    with pytest.raises(RegistryError):
        r._assert_provides_registered()  # the post-import check, called directly
