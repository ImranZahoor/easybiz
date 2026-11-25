import pytest
from django_tenants.utils import tenant_context

from easybiz.core.api import paging
from easybiz.core.audit.models import AuditLog


def _rows(n):
    for i in range(n):
        AuditLog.objects.create(action=f"a{i:02d}", entity="x", entity_id=str(i))


def test_pages_through_all_rows_once(synced, db_tenant):
    with tenant_context(db_tenant):
        _rows(5)
        seen, cursor = [], None
        while True:
            page = paging.paginate(AuditLog.objects.all(), limit=2, cursor=cursor, order_by="-at")
            seen += [r.entity_id for r in page["items"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert sorted(seen) == [str(i) for i in range(5)] and len(seen) == 5


def test_limit_capped_at_200(synced, db_tenant):
    with tenant_context(db_tenant):
        _rows(201)
        page = paging.paginate(AuditLog.objects.all(), limit=10_000, order_by="-at")
        assert len(page["items"]) == 200 and page["next_cursor"] is not None


def test_last_page_has_no_cursor(synced, db_tenant):
    with tenant_context(db_tenant):
        _rows(2)
        page = paging.paginate(AuditLog.objects.all(), limit=50, order_by="-at")
        assert len(page["items"]) == 2 and page["next_cursor"] is None


def test_malformed_cursor_rejected(synced, db_tenant):
    with tenant_context(db_tenant):
        with pytest.raises(paging.CursorError):
            paging.paginate(AuditLog.objects.all(), cursor="not-base64!!", order_by="-at")


def test_cursor_with_wrong_field_value_rejected(synced, db_tenant):
    # a well-formed cursor carrying a value invalid for the field (e.g. replayed across tools)
    with tenant_context(db_tenant):
        bad = paging._encode("not-a-date", "11111111-1111-1111-1111-111111111111")
        with pytest.raises(paging.CursorError):
            paging.paginate(AuditLog.objects.all(), cursor=bad, order_by="-at")


def test_tie_on_sort_value_paged_by_pk(synced, db_tenant):
    with tenant_context(db_tenant):
        for i in range(4):
            AuditLog.objects.create(action="same", entity="x", entity_id=str(i))
        seen, cursor = [], None
        while True:
            page = paging.paginate(
                AuditLog.objects.all(), limit=1, cursor=cursor, order_by="action"
            )
            seen += [r.entity_id for r in page["items"]]
            cursor = page["next_cursor"]
            if cursor is None:
                break
        assert len(set(seen)) == 4
