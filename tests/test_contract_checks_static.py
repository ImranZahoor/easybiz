from easybiz.core.testing import checks


def test_timesheets_passes_static_checks():
    for fn in (
        checks.check_manifest_and_app_label,
        checks.check_endpoint_permissions,
        checks.check_events,
        checks.check_no_cross_imports,
        checks.check_no_cross_fk_and_prefix,
    ):
        assert fn("timesheets") == [], fn.__name__
    assert checks.check_no_cross_imports("demo") == []


def test_cross_import_flagged(tmp_path):
    pkg = tmp_path / "badmod"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "x.py").write_text("from easybiz.modules.timesheets import queries\n")
    assert checks._scan_imports(str(pkg), "badmod")  # returns offending import(s)


def test_endpoint_permission_undeclared_flagged():
    bad = checks._undeclared_endpoint_perms(
        perms_used={"demo.secret"}, declared={"demo.widget.read"}
    )
    assert bad == {"demo.secret"}


def test_endpoint_permission_core_allowed():
    bad = checks._undeclared_endpoint_perms(perms_used={"core.user.read"}, declared=set())
    assert bad == set()  # core.* is allowed even if not declared by the module


def test_cross_fk_flagged():
    from django.db import models

    class _CrossFk(models.Model):
        role = models.ForeignKey("iam.Role", on_delete=models.CASCADE)

        class Meta:
            app_label = "hr"

    assert checks._relation_offenders(_CrossFk, module_id="hr")  # FK to iam -> non-empty


def test_missing_handler_flagged():
    from easybiz.core.kernel.manifest import parse_manifest

    m = parse_manifest(
        {
            "id": "hr",
            "name": "HR",
            "version": "1.0.0",
            "events": {"subscribes": ["core.nonexistent.event"]},
        }
    )
    assert checks._missing_handlers(m)  # no handler registered -> non-empty
