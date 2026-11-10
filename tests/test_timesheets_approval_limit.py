from datetime import date
from decimal import Decimal

import pytest
from django.test import Client
from django_tenants.utils import tenant_context

from easybiz.core.iam import service as iam
from easybiz.core.iam.enums import PolicyEffect
from easybiz.core.iam.models import Role, RolePermission, UserAttribute, UserRole
from easybiz.core.kernel import lifecycle
from easybiz.modules.timesheets import commands
from easybiz.modules.timesheets.enums import EntryStatus
from easybiz.modules.timesheets.models import Entry, Project
from easybiz.modules.timesheets.types import ReviewEntryParams

PERM = "timesheets.entry.approve"
GT = {"op": "gt", "left": {"var": "resource.hours"}, "right": {"var": "subject.approval_limit"}}
AUTHOR = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
REVIEWER = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _enable(tenant):
    lifecycle.enable_module(tenant, "timesheets", actor_id=None)


def _submitted_entry(hours):
    project = Project.objects.create(code="ABC", name="ABC")
    return Entry.objects.create(
        user_id=AUTHOR,
        project=project,
        work_date=date(2026, 11, 10),
        hours=Decimal(hours),
        note="",
        status=EntryStatus.SUBMITTED,
    )


def _reviewer(limit=None):
    role = Role.objects.create(name="appr")
    RolePermission.objects.create(role=role, permission=PERM)
    UserRole.objects.create(user_id=REVIEWER, role=role)
    if limit is not None:
        UserAttribute.objects.create(user_id=REVIEWER, key="approval_limit", value=limit)


def test_approve_over_limit_is_403(synced, db_tenant):
    with tenant_context(db_tenant):
        _enable(db_tenant)
        _reviewer(limit=8)
        iam.create_policy(
            db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, actor_id=None
        )
        entry = _submitted_entry(10)
        with pytest.raises(commands.TimesheetError) as exc:
            commands.approve_entry(ReviewEntryParams(reviewer_id=REVIEWER, entry_id=entry.id))
        assert exc.value.status == 403


def test_approve_within_limit_succeeds(synced, db_tenant):
    with tenant_context(db_tenant):
        _enable(db_tenant)
        _reviewer(limit=8)
        iam.create_policy(
            db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, actor_id=None
        )
        entry = _submitted_entry(6)
        out = commands.approve_entry(ReviewEntryParams(reviewer_id=REVIEWER, entry_id=entry.id))
        assert out.status == EntryStatus.APPROVED


def test_reviewer_without_limit_unaffected(synced, db_tenant):
    with tenant_context(db_tenant):
        _enable(db_tenant)
        _reviewer(limit=None)  # no approval_limit attribute
        iam.create_policy(
            db_tenant, permission=PERM, effect=PolicyEffect.DENY_IF, condition=GT, actor_id=None
        )
        entry = _submitted_entry(10)
        out = commands.approve_entry(ReviewEntryParams(reviewer_id=REVIEWER, entry_id=entry.id))
        assert out.status == EntryStatus.APPROVED


# --- HTTP smoke --------------------------------------------------------------


def _login(slug, email, password="change-me-now"):
    return (
        Client()
        .post(
            "/api/auth/login",
            data={"email": email, "password": password},
            content_type="application/json",
            HTTP_HOST=f"{slug}.localhost",
        )
        .json()["access_token"]
    )


def _req(method, path, token, slug, body=None):
    kw = {"HTTP_HOST": f"{slug}.localhost", "HTTP_AUTHORIZATION": f"Bearer {token}"}
    if body is not None:
        kw["data"] = body
        kw["content_type"] = "application/json"
    return getattr(Client(), method)(path, **kw)


def test_http_smoke_approval_limit(synced, provision):
    slug = "tslimit"
    provision(slug=slug, modules=("timesheets",))
    owner = _login(slug, f"owner@{slug}.test")

    _req(
        "post",
        "/api/core/users",
        owner,
        slug,
        {
            "email": f"appr@{slug}.test",
            "password": "change-me-now",
            "roles": ["timesheet_approver"],
        },
    )
    appr_id = next(
        u["id"]
        for u in _req("get", "/api/core/users", owner, slug).json()
        if u["email"] == f"appr@{slug}.test"
    )
    _req(
        "put",
        f"/api/core/users/{appr_id}/attributes",
        owner,
        slug,
        {"attributes": {"approval_limit": 8}},
    )
    _req(
        "post",
        "/api/core/policies",
        owner,
        slug,
        {"permission": PERM, "effect": "deny_if", "condition": GT},
    )

    _req("post", "/api/timesheets/projects", owner, slug, {"code": "abc", "name": "ABC"})
    proj = _req("get", "/api/timesheets/projects", owner, slug).json()[0]["id"]

    def submit_entry(hours):
        ent = _req(
            "post",
            "/api/timesheets/entries",
            owner,
            slug,
            {"project_id": proj, "work_date": "2026-11-10", "hours": hours},
        ).json()
        _req("post", f"/api/timesheets/entries/{ent['id']}/submit", owner, slug)
        return ent["id"]

    appr = _login(slug, f"appr@{slug}.test")
    over = submit_entry(10)
    assert _req("post", f"/api/timesheets/entries/{over}/approve", appr, slug).status_code == 403
    under = submit_entry(6)
    assert _req("post", f"/api/timesheets/entries/{under}/approve", appr, slug).status_code == 200
