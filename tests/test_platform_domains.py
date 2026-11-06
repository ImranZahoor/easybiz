from django.test import Client

from tests.test_platform_auth_api import plat_delete, plat_post
from tests.test_platform_tenants_write import _cleanup, _create


def _domains(resp):
    return {d["domain"]: d["is_primary"] for d in resp.json()["domains"]}


def _add(token, slug, domain, is_primary=False):
    return plat_post(
        f"/api/platform/tenants/{slug}/domains", token, {"domain": domain, "is_primary": is_primary}
    )


def test_add_domain_normalised_and_primary_switch(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")
    r = _add(token, "neo", "NEO-ALT.localhost", is_primary=True)
    assert r.status_code == 201
    doms = _domains(r)
    assert (
        doms["neo-alt.localhost"] is True and doms["neo.localhost"] is False
    )  # normalised + switched
    # the new host now serves the tenant
    login = Client().post(
        "/api/auth/login",
        data={"email": "owner@neo.test", "password": "change-me-now"},
        content_type="application/json",
        HTTP_HOST="neo-alt.localhost",
    )
    assert login.status_code == 200


def test_add_domain_duplicate_and_invalid(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")
    assert _add(token, "neo", "neo.localhost").status_code == 409  # already in use
    assert _add(token, "neo", "http://neo2.localhost").status_code == 422  # invalid host


def test_remove_domain_rules(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")
    _add(token, "neo", "neo2.localhost")
    r = plat_delete("/api/platform/tenants/neo/domains/neo2.localhost", token)
    assert r.status_code == 200 and "neo2.localhost" not in _domains(r)  # non-primary removed
    assert (
        plat_delete("/api/platform/tenants/neo/domains/ghost.localhost", token).status_code == 422
    )
    assert (
        plat_delete("/api/platform/tenants/neo/domains/neo.localhost", token).status_code == 409
    )  # last


def test_remove_primary_promotes_another(admin, synced, request):
    _, token = admin
    _cleanup(request, "neo", emails=["owner@neo.test"])
    _create(token, "neo")
    _add(token, "neo", "neo2.localhost")  # secondary
    r = plat_delete("/api/platform/tenants/neo/domains/neo.localhost", token)  # remove the primary
    assert r.status_code == 200 and _domains(r).get("neo2.localhost") is True  # promoted
