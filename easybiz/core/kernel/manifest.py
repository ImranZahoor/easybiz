from __future__ import annotations

import re
from dataclasses import dataclass, field

_VERSION_RE = re.compile(r"^\d+(\.\d+){0,2}$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_RESERVED_IDS = {"core", "auth", "platform", "admin", "docs", "openapi"}

Dep = tuple[str, str]


class ManifestError(Exception):
    """Raised when a manifest or version/range is invalid."""


@dataclass(frozen=True, order=True)
class Version:
    parts: tuple[int, int, int]

    @classmethod
    def parse(cls, raw: str) -> Version:
        if not isinstance(raw, str) or not _VERSION_RE.match(raw):
            raise ManifestError(f"invalid version: {raw!r}")
        nums = [int(p) for p in raw.split(".")]
        nums += [0] * (3 - len(nums))
        return cls((nums[0], nums[1], nums[2]))


@dataclass(frozen=True)
class VersionRange:
    """A version constraint with an inclusive lower and exclusive upper bound."""

    low: Version | None
    high: Version | None  # exclusive

    def contains(self, v: Version) -> bool:
        if self.low is not None and v < self.low:
            return False
        if self.high is not None and v >= self.high:
            return False
        return True

    @classmethod
    def parse(cls, raw: str) -> VersionRange:
        raw = (raw or "*").strip()
        if raw == "*":
            return cls(None, None)
        if raw.startswith(">="):
            return cls(Version.parse(raw[2:]), None)
        if raw.startswith("^"):
            return cls._caret(raw[1:])
        if raw.startswith("~"):
            return cls._tilde(raw[1:])
        exact = Version.parse(raw)
        major, minor, patch = exact.parts
        return cls(exact, Version((major, minor, patch + 1)))

    @classmethod
    def _caret(cls, base: str) -> VersionRange:
        low = Version.parse(base)
        major, minor, patch = low.parts
        if major > 0:
            high = Version((major + 1, 0, 0))
        elif minor > 0:
            high = Version((0, minor + 1, 0))
        else:
            high = Version((0, 0, patch + 1))
        return cls(low, high)

    @classmethod
    def _tilde(cls, base: str) -> VersionRange:
        low = Version.parse(base)
        major, minor, _ = low.parts
        return cls(low, Version((major, minor + 1, 0)))


# Top-level manifest keys the parser reads (the schema file documents these plus
# forward-declared keys for unbuilt features). Kept in sync by a test.
KNOWN_KEYS = frozenset(
    {
        "id",
        "name",
        "version",
        "manifest_version",
        "requires_core",
        "requires",
        "optional",
        "provides",
        "consumes",
        "permissions",
        "roles",
        "events",
        "menu",
        "extension_points",
        "extends",
    }
)

# (contract, version) a module provides; (contract, range, optional) a module consumes.
Provide = tuple[str, str]
Consume = tuple[str, str, bool]


@dataclass(frozen=True)
class Manifest:
    id: str
    version: str
    name: str
    manifest_version: int = 1
    requires_core: str | None = None
    requires: list[Dep] = field(default_factory=list)
    optional: list[Dep] = field(default_factory=list)
    provides: list[Provide] = field(default_factory=list)
    consumes: list[Consume] = field(default_factory=list)
    permissions: list[tuple[str, str]] = field(default_factory=list)
    sensitive_permissions: frozenset[str] = frozenset()
    roles: list[dict] = field(default_factory=list)
    publishes: list[str] = field(default_factory=list)
    subscribes: list[str] = field(default_factory=list)
    menu: list[dict] = field(default_factory=list)
    extension_points: list[dict] = field(default_factory=list)
    extends: list[dict] = field(default_factory=list)
    package: str | None = None

    def to_dict(self) -> dict:
        """Serialise back to a plain JSON-storable manifest dict (for the catalog)."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "manifest_version": self.manifest_version,
            "requires_core": self.requires_core,
            "requires": [list(d) for d in self.requires],
            "optional": [list(d) for d in self.optional],
            "provides": [list(p) for p in self.provides],
            "consumes": [list(c) for c in self.consumes],
            "permissions": [list(p) for p in self.permissions],
            "roles": self.roles,
            "publishes": self.publishes,
            "subscribes": self.subscribes,
            "menu": self.menu,
            "extension_points": self.extension_points,
            "extends": self.extends,
        }


def _deps(raw: list[dict] | None, kind: str) -> list[Dep]:
    out: list[Dep] = []
    for entry in raw or []:
        module = entry.get("module")
        if not module:
            raise ManifestError(f"{kind} entry missing 'module'")
        rng = entry.get("range", "*")
        VersionRange.parse(rng)  # validate the range now
        out.append((module, rng))
    return out


def _provides(raw: list | None, mv: int) -> list[Provide]:
    out: list[Provide] = []
    for entry in raw or []:
        if mv >= 2:
            if not isinstance(entry, dict) or not entry.get("contract"):
                raise ManifestError("v2 provides entry must be an object with a 'contract'")
            ver = entry.get("version", "1.0.0")
            Version.parse(ver)  # validate now
            out.append((entry["contract"], ver))
        else:
            if not isinstance(entry, str):
                raise ManifestError("v1 provides entry must be a contract-name string")
            out.append((entry, "1.0.0"))
    return out


def _consumes(raw: list | None, mv: int) -> list[Consume]:
    out: list[Consume] = []
    for entry in raw or []:
        if mv >= 2:
            if not isinstance(entry, dict) or not entry.get("contract"):
                raise ManifestError("v2 consumes entry must be an object with a 'contract'")
            rng = entry.get("range", "*")
            VersionRange.parse(rng)  # validate now
            optional = entry.get("optional", False)
            if not isinstance(optional, bool):
                raise ManifestError("consumes 'optional' must be a boolean")
            out.append((entry["contract"], rng, optional))
        else:
            if not isinstance(entry, str):
                raise ManifestError("v1 consumes entry must be a contract-name string")
            out.append((entry, "*", False))
    return out


def _extension_points(raw: list | None) -> list[dict]:
    out: list[dict] = []
    for entry in raw or []:
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("contract"):
            raise ManifestError("extension_points entry needs 'name' and 'contract'")
        Version.parse(entry.get("version", "1.0.0"))  # validate now
        out.append(entry)
    return out


def _extends(raw: list | None) -> list[dict]:
    out: list[dict] = []
    for entry in raw or []:
        if not isinstance(entry, dict) or not entry.get("point"):
            raise ManifestError("extends entry needs a 'point'")
        out.append(entry)
    return out


def parse_manifest(data: dict, *, package: str | None = None) -> Manifest:
    """Validate a manifest dict and return a Manifest, or raise ManifestError."""
    mid = data.get("id")
    if not mid or not _ID_RE.match(mid):
        raise ManifestError(f"invalid module id: {mid!r}")
    if mid in _RESERVED_IDS:
        raise ManifestError(f"reserved module id: {mid!r}")
    version = data.get("version")
    if not version or not _VERSION_RE.match(version):
        raise ManifestError(f"invalid version: {version!r}")

    manifest_version = data.get("manifest_version", 1)
    if manifest_version not in (1, 2):
        raise ManifestError(f"unsupported manifest_version: {manifest_version!r}")
    requires_core = data.get("requires_core")
    if requires_core is not None:
        VersionRange.parse(requires_core)  # validate the range now

    requires = _deps(data.get("requires"), "requires")
    optional = _deps(data.get("optional"), "optional")

    req_ids = [m for m, _ in requires]
    opt_ids = [m for m, _ in optional]
    if mid in req_ids or mid in opt_ids:
        raise ManifestError(f"module {mid!r} cannot depend on itself")
    if len(req_ids) != len(set(req_ids)):
        raise ManifestError("duplicate requires entry")
    if len(opt_ids) != len(set(opt_ids)):
        raise ManifestError("duplicate optional entry")
    if set(req_ids) & set(opt_ids):
        raise ManifestError("optional may not repeat a requires entry")

    permissions: list[tuple[str, str]] = []
    sensitive: set[str] = set()
    for p in data.get("permissions", []):
        code = p.get("code")
        if not code:
            raise ManifestError("permission entry missing 'code'")
        if not code.startswith(f"{mid}."):
            raise ManifestError(f"permission {code!r} must start with {mid!r}.")
        flag = p.get("sensitive", False)
        if not isinstance(flag, bool):
            raise ManifestError(f"permission {code!r} 'sensitive' must be a boolean")
        if flag:
            sensitive.add(code)
        permissions.append((code, p.get("description", "")))
    declared = {code for code, _ in permissions}

    roles = data.get("roles", [])
    for role in roles:
        if not role.get("name"):
            raise ManifestError("role entry missing 'name'")
        for perm in role.get("permissions", []):
            if perm not in declared:
                raise ManifestError(
                    f"role {role.get('name')!r} uses undeclared permission {perm!r}"
                )

    events = data.get("events", {}) or {}
    publishes = list(events.get("publishes", []))
    for name in publishes:
        if not name.startswith(f"{mid}."):
            raise ManifestError(f"event {name!r} must start with {mid!r}.")
    subscribes = list(events.get("subscribes", []))

    return Manifest(
        id=mid,
        version=version,
        name=data.get("name") or mid,
        manifest_version=manifest_version,
        requires_core=requires_core,
        requires=requires,
        optional=optional,
        provides=_provides(data.get("provides"), manifest_version),
        consumes=_consumes(data.get("consumes"), manifest_version),
        permissions=permissions,
        sensitive_permissions=frozenset(sensitive),
        roles=roles,
        publishes=publishes,
        subscribes=subscribes,
        menu=data.get("menu", []),
        extension_points=_extension_points(data.get("extension_points")),
        extends=_extends(data.get("extends")),
        package=package,
    )
