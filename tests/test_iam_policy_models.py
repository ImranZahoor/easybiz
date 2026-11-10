import pytest
from django.db import IntegrityError
from django_tenants.utils import tenant_context

from easybiz.core.iam.enums import PolicyEffect
from easybiz.core.iam.models import Policy, UserAttribute

USER = "11111111-1111-1111-1111-111111111111"


def test_policy_and_attribute_rows(synced, db_tenant):
    with tenant_context(db_tenant):
        p = Policy.objects.create(
            permission="timesheets.entry.approve",
            effect=PolicyEffect.DENY_IF,
            condition={
                "op": "gt",
                "left": {"var": "resource.hours"},
                "right": {"var": "subject.approval_limit"},
            },
        )
        assert p.is_active is True and p.priority == 0
        UserAttribute.objects.create(user_id=USER, key="approval_limit", value=8)
        with pytest.raises(IntegrityError):
            UserAttribute.objects.create(user_id=USER, key="approval_limit", value=9)
