import pytest

from easybiz.core.kernel.manifest import ManifestError, Version, VersionRange


def _in(range_str, version_str):
    return VersionRange.parse(range_str).contains(Version.parse(version_str))


def test_exact_range():
    assert _in("1.2.3", "1.2.3")
    assert not _in("1.2.3", "1.2.4")


def test_padding_treats_1_as_1_0_0():
    assert Version.parse("1") == Version.parse("1.0.0")
    assert _in("1", "1.0.0")


def test_caret_major():
    assert _in("^1.2", "1.2.0") and _in("^1.2", "1.9.9")
    assert not _in("^1.2", "2.0.0")
    assert not _in("^1.2", "1.1.0")


def test_caret_zero_minor():
    assert _in("^0.2.1", "0.2.1") and _in("^0.2.1", "0.2.9")
    assert not _in("^0.2.1", "0.3.0")


def test_caret_zero_zero_patch():
    assert _in("^0.0.3", "0.0.3")
    assert not _in("^0.0.3", "0.0.4")


def test_tilde():
    assert _in("~1.2.3", "1.2.3") and _in("~1.2.3", "1.2.9")
    assert not _in("~1.2.3", "1.3.0")


def test_gte_and_wildcard():
    assert _in(">=1.2", "1.2.0") and _in(">=1.2", "9.9.9")
    assert not _in(">=1.2", "1.1.9")
    assert _in("*", "0.0.1") and _in("*", "99.0.0")


def test_invalid_version_rejected():
    with pytest.raises(ManifestError):
        Version.parse("1.2.3.4")
    with pytest.raises(ManifestError):
        Version.parse("x")


# --- manifest validation (Task 2) -------------------------------------------

from easybiz.core.kernel.manifest import parse_manifest  # noqa: E402

RESERVED = {"core", "auth", "platform", "admin", "docs", "openapi"}


def _m(**over):
    base = {"id": "hr", "version": "1.0.0"}
    base.update(over)
    return base


def test_minimal_manifest_defaults_name_to_id():
    m = parse_manifest(_m())
    assert m.id == "hr" and m.name == "hr" and m.version == "1.0.0"


def test_missing_id_rejected():
    with pytest.raises(ManifestError):
        parse_manifest({"version": "1.0.0"})


@pytest.mark.parametrize("bad", ["A", "1hr", "a", "x" * 32, "hr-x"])
def test_bad_id_rejected(bad):
    with pytest.raises(ManifestError):
        parse_manifest(_m(id=bad))


@pytest.mark.parametrize("rid", sorted(RESERVED))
def test_reserved_id_rejected(rid):
    with pytest.raises(ManifestError):
        parse_manifest(_m(id=rid))


def test_bad_version_rejected():
    with pytest.raises(ManifestError):
        parse_manifest(_m(version="1.2.3.4"))


def test_permission_prefix_enforced():
    with pytest.raises(ManifestError):
        parse_manifest(_m(permissions=[{"code": "other.read", "description": "x"}]))


def test_event_prefix_enforced():
    with pytest.raises(ManifestError):
        parse_manifest(_m(events={"publishes": ["other.thing.done"], "subscribes": []}))


def test_role_permission_must_be_declared():
    with pytest.raises(ManifestError):
        parse_manifest(
            _m(
                permissions=[{"code": "hr.read", "description": "x"}],
                roles=[{"name": "r", "description": "d", "permissions": ["hr.write"]}],
            )
        )


def test_self_dependency_rejected():
    with pytest.raises(ManifestError):
        parse_manifest(_m(requires=[{"module": "hr", "range": "*"}]))


def test_duplicate_dependency_rejected():
    with pytest.raises(ManifestError):
        parse_manifest(
            _m(requires=[{"module": "a1", "range": "*"}, {"module": "a1", "range": "^1"}])
        )


def test_optional_may_not_repeat_requires():
    with pytest.raises(ManifestError):
        parse_manifest(_m(requires=[{"module": "a1"}], optional=[{"module": "a1"}]))


def test_requires_range_defaults_to_wildcard():
    m = parse_manifest(_m(requires=[{"module": "a1"}]))
    assert m.requires == [("a1", "*")]


# --- registry graph (Task 3) ------------------------------------------------

from easybiz.core.kernel.registry import Registry, RegistryError  # noqa: E402


def _reg(*manifests):
    reg = Registry()
    for data in manifests:
        reg.add(parse_manifest(data))
    return reg


def test_load_order_dependencies_first():
    reg = _reg(
        {"id": "payroll", "version": "1.0.0", "requires": [{"module": "hr", "range": "^1"}]},
        {"id": "hr", "version": "1.2.0"},
    )
    order = reg.load_order()
    assert order.index("hr") < order.index("payroll")


def test_missing_hard_dependency_fails_fast():
    reg = _reg({"id": "payroll", "version": "1.0.0", "requires": [{"module": "hr"}]})
    with pytest.raises(RegistryError, match="not installed"):
        reg.load_order()


def test_incompatible_dependency_version_fails():
    reg = _reg(
        {"id": "payroll", "version": "1.0.0", "requires": [{"module": "hr", "range": "^2"}]},
        {"id": "hr", "version": "1.2.0"},
    )
    with pytest.raises(RegistryError, match="1.2.0"):
        reg.load_order()


def test_dependency_cycle_detected():
    reg = _reg(
        {"id": "aa", "version": "1.0.0", "requires": [{"module": "bb"}]},
        {"id": "bb", "version": "1.0.0", "requires": [{"module": "aa"}]},
    )
    with pytest.raises(RegistryError, match="cycle"):
        reg.load_order()


def test_dependents_of():
    reg = _reg(
        {"id": "hr", "version": "1.0.0"},
        {"id": "payroll", "version": "1.0.0", "requires": [{"module": "hr"}]},
        {"id": "timesheets", "version": "1.0.0", "optional": [{"module": "hr"}]},
    )
    assert reg.dependents_of("hr") == ["payroll"]  # requires only, not optional


# --- runtime wiring (Task 4) ------------------------------------------------


def test_module_id_for_core_prefix():
    reg = Registry()
    assert reg.module_id_for("easybiz.core.kernel.apps") == "core"


def test_module_id_for_longest_module_prefix():
    reg = Registry()
    reg.add(
        parse_manifest(
            {"id": "timesheets", "version": "0.1.0"}, package="easybiz.modules.timesheets"
        )
    )
    assert reg.module_id_for("easybiz.modules.timesheets.handlers") == "timesheets"


def test_add_handler_rejects_undeclared_subscription():
    reg = Registry()
    reg.add(
        parse_manifest(
            {"id": "timesheets", "version": "0.1.0"}, package="easybiz.modules.timesheets"
        )
    )

    def handler(event):
        return None

    handler.__module__ = "easybiz.modules.timesheets.handlers"
    with pytest.raises(RegistryError, match="not declared"):
        reg.add_handler("timesheets.entry.approved", handler)


def test_discovery_returns_explicit_packages():
    from easybiz.core.kernel.discovery import discover_module_packages

    assert discover_module_packages(["easybiz.modules.timesheets"]) == [
        "easybiz.modules.timesheets"
    ]


def test_module_id_for_unknown_returns_none():
    assert Registry().module_id_for("some.random.thirdparty") is None


def test_add_handler_rejects_unknown_module():
    reg = Registry()

    def handler(event):
        return None

    handler.__module__ = "some.random.thirdparty"
    with pytest.raises(RegistryError, match="no known module"):
        reg.add_handler("whatever.event", handler)


def test_add_handler_allows_core_handler():
    reg = Registry()

    def handler(event):
        return None

    handler.__module__ = "easybiz.core.events.service"
    reg.add_handler("core.module.enabled", handler)
    assert reg._handlers["core.module.enabled"] == [handler]


def test_permission_entry_missing_code_rejected():
    with pytest.raises(ManifestError):
        parse_manifest(_m(permissions=[{"description": "no code"}]))
