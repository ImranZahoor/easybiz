from django.conf import settings

from easybiz.core.contracts import AttendanceProvider


def test_contract_declares_version():
    assert AttendanceProvider.__contract_version__ == "1.0.0"


def test_core_version_setting():
    assert settings.EASYBIZ_CORE_VERSION == "1.0.0"
