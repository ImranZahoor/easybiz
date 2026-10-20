import importlib


def test_secret_key_default_is_long_enough():
    settings = importlib.import_module("config.settings")
    assert len(settings.SECRET_KEY) >= 32


def test_db_name_is_test_db_under_pytest():
    settings = importlib.import_module("config.settings")
    assert settings.DATABASES["default"]["NAME"] == "easybiz_test"
