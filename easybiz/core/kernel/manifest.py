"""Module manifest parsing, validation, and version-range semantics."""

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


@dataclass(frozen=True)
class Manifest:
    id: str
    version: str
    name: str
    requires: list[Dep] = field(default_factory=list)
    optional: list[Dep] = field(default_factory=list)
    provides: list[str] = field(default_factory=list)
    consumes: list[str] = field(default_factory=list)
    permissions: list[tuple[str, str]] = field(default_factory=list)
    roles: list[dict] = field(default_factory=list)
    publishes: list[str] = field(default_factory=list)
    subscribes: list[str] = field(default_factory=list)
    menu: list[dict] = field(default_factory=list)
    package: str | None = None

    def to_dict(self) -> dict:
        """Serialise back to a plain JSON-storable manifest dict (for the catalog)."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "requires": [list(d) for d in self.requires],
            "optional": [list(d) for d in self.optional],
            "provides": self.provides,
            "consumes": self.consumes,
            "permissions": [list(p) for p in self.permissions],
            "roles": self.roles,
            "publishes": self.publishes,
            "subscribes": self.subscribes,
            "menu": self.menu,
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
    for p in data.get("permissions", []):
        code = p.get("code")
        if not code:
            raise ManifestError("permission entry missing 'code'")
        if not code.startswith(f"{mid}."):
            raise ManifestError(f"permission {code!r} must start with {mid!r}.")
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
        requires=requires,
        optional=optional,
        provides=list(data.get("provides", [])),
        consumes=list(data.get("consumes", [])),
        permissions=permissions,
        roles=roles,
        publishes=publishes,
        subscribes=subscribes,
        menu=data.get("menu", []),
        package=package,
    )
