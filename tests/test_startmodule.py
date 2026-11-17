import json

import pytest

from easybiz.core.kernel import scaffold
from easybiz.core.kernel.manifest import parse_manifest
from easybiz.core.testing import checks


def test_scaffold_generates_contract_clean_module(tmp_path):
    dest = scaffold.scaffold_module("widgets", base_dir=tmp_path)
    assert (dest / "manifest.json").exists()
    assert (dest / "migrations" / "0001_initial.py").exists()
    manifest = parse_manifest(json.loads((dest / "manifest.json").read_text()))
    assert manifest.id == "widgets" and manifest.manifest_version == 2
    assert 'label = "widgets"' in (dest / "apps.py").read_text()  # app label == id
    assert checks._scan_imports(str(dest), "widgets") == []  # no cross-module imports


def test_scaffold_refuses_overwrite(tmp_path):
    scaffold.scaffold_module("widgets", base_dir=tmp_path)
    with pytest.raises(FileExistsError):
        scaffold.scaffold_module("widgets", base_dir=tmp_path)


def test_scaffold_rejects_bad_id(tmp_path):
    for bad in ("Widgets", "1bad", "core", "auth"):
        with pytest.raises(ValueError):
            scaffold.scaffold_module(bad, base_dir=tmp_path)


def test_add_to_env_appends_package(tmp_path):
    env = tmp_path / ".env"
    env.write_text("EASYBIZ_MODULES=easybiz.modules.timesheets,easybiz.modules.demo\n")
    assert scaffold.add_to_env("easybiz.modules.widgets", env) is True
    assert "easybiz.modules.widgets" in env.read_text()


def test_add_to_env_no_line_returns_false(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER=1\n")
    assert scaffold.add_to_env("easybiz.modules.widgets", env) is False


def test_requires_optional_in_manifest(tmp_path):
    dest = scaffold.scaffold_module("widgets", base_dir=tmp_path, requires=["hr"], optional=["demo"])
    m = parse_manifest(json.loads((dest / "manifest.json").read_text()))
    assert [d for d, _ in m.requires] == ["hr"] and [d for d, _ in m.optional] == ["demo"]
