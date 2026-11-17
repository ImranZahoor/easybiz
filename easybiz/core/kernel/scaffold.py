from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

from easybiz.core.kernel.manifest import _ID_RE, _RESERVED_IDS

_APPS = '''from django.apps import AppConfig


class __CLASS__Config(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "__PKG__"
    label = "__MID__"
'''

_MODELS = '''import uuid

from django.db import models


class Thing(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
'''

_API = '''from ninja import Router, Schema

from easybiz.core.api.security import perm
from __PKG__.models import Thing

router = Router()


class ThingOut(Schema):
    id: str
    name: str


@router.get("/things", auth=perm("__MID__.thing.read"), response=list[ThingOut])
def list_things(request):
    """Every thing, newest first."""
    return [ThingOut(id=str(t.id), name=t.name) for t in Thing.objects.order_by("-created_at")]
'''

_HANDLERS = '''"""Event handlers for the __MID__ module (none yet)."""
'''

_PROVIDERS = '''"""Capability providers and extension contributions for the __MID__ module (none yet)."""
'''

_MIGRATION = '''import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="Thing",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        primary_key=True, default=uuid.uuid4, editable=False, serialize=False
                    ),
                ),
                ("name", models.CharField(max_length=200)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
'''

_TEST = '''from easybiz.core.testing import run_module_contract_checks


def test_module_satisfies_contract():
    assert run_module_contract_checks("__MID__") == []
'''


def _render(template: str, module_id: str, package: str) -> str:
    cls = "".join(p.title() for p in module_id.split("_"))
    return template.replace("__CLASS__", cls).replace("__PKG__", package).replace("__MID__", module_id)


def _manifest(module_id: str, requires: Iterable[str], optional: Iterable[str]) -> dict:
    return {
        "id": module_id,
        "name": module_id.title(),
        "version": "0.1.0",
        "manifest_version": 2,
        "requires": [{"module": r} for r in requires],
        "optional": [{"module": o} for o in optional],
        "permissions": [{"code": f"{module_id}.thing.read", "description": f"View {module_id} things"}],
        "roles": [
            {
                "name": f"{module_id}_viewer",
                "description": f"Views {module_id} things",
                "permissions": [f"{module_id}.thing.read"],
            }
        ],
        "events": {"publishes": [], "subscribes": []},
        "menu": [{"label": module_id.title(), "route": f"/{module_id}", "permission": f"{module_id}.thing.read"}],
    }


def scaffold_module(
    module_id: str,
    *,
    base_dir: Path,
    package_root: str = "easybiz.modules",
    requires: Iterable[str] = (),
    optional: Iterable[str] = (),
) -> Path:
    """Generate a worked-sample, contract-clean module package; never overwrites an existing dir."""
    if not _ID_RE.match(module_id) or module_id in _RESERVED_IDS:
        raise ValueError(f"invalid or reserved module id: {module_id!r}")
    dest = Path(base_dir) / module_id
    if dest.exists():
        raise FileExistsError(f"{dest} already exists")
    package = f"{package_root}.{module_id}"
    (dest / "migrations").mkdir(parents=True)
    (dest / "tests").mkdir()

    (dest / "__init__.py").write_text("")
    (dest / "migrations" / "__init__.py").write_text("")
    (dest / "tests" / "__init__.py").write_text("")
    (dest / "manifest.json").write_text(
        json.dumps(_manifest(module_id, requires, optional), indent=2) + "\n"
    )
    for name, template in (
        ("apps.py", _APPS),
        ("models.py", _MODELS),
        ("api.py", _API),
        ("handlers.py", _HANDLERS),
        ("providers.py", _PROVIDERS),
    ):
        (dest / name).write_text(_render(template, module_id, package))
    (dest / "migrations" / "0001_initial.py").write_text(_render(_MIGRATION, module_id, package))
    (dest / "tests" / "test_contract.py").write_text(_render(_TEST, module_id, package))
    return dest


def add_to_env(module_package: str, env_path: Path) -> bool:
    """Append ``module_package`` to the EASYBIZ_MODULES line in ``env_path``; False if absent."""
    env_path = Path(env_path)
    if not env_path.exists():
        return False
    lines = env_path.read_text().splitlines()
    for i, line in enumerate(lines):
        if line.startswith("EASYBIZ_MODULES="):
            packages = line[len("EASYBIZ_MODULES=") :].split(",") if "=" in line else []
            packages = [p for p in packages if p]
            if module_package not in packages:
                packages.append(module_package)
            lines[i] = "EASYBIZ_MODULES=" + ",".join(packages)
            env_path.write_text("\n".join(lines) + "\n")
            return True
    return False
