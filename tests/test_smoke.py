import django
from django.conf import settings


def test_django_boots_and_system_checks_pass():
    django.setup()
    from django.core.management import call_command

    call_command("check")  # raises SystemCheckError on any error-level issue


def test_router_registered_for_django_tenants():
    assert settings.TENANT_SYNC_ROUTER in settings.DATABASE_ROUTERS


def test_contenttypes_installed():
    assert "django.contrib.contenttypes" in settings.INSTALLED_APPS
