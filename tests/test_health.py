from django.test import Client


def test_health_on_platform_host():
    resp = Client().get("/health", HTTP_HOST="localhost")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "scope": "platform"}
