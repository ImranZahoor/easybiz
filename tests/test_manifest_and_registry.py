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
