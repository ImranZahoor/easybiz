"""Module manifest parsing, validation, and version-range semantics."""

from __future__ import annotations

import re
from dataclasses import dataclass

_VERSION_RE = re.compile(r"^\d+(\.\d+){0,2}$")


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
