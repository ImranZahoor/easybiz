import logging
import time

from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context

from easybiz.core.events.service import dispatch_pending
from easybiz.core.tenancy.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Deliver outbox events for every active tenant (polling; Celery is F15)."""

    def add_arguments(self, parser) -> None:
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=2)

    def handle(self, *args, **options) -> None:
        public = get_public_schema_name()
        while True:
            schemas = list(
                Tenant.objects.filter(is_active=True)
                .exclude(schema_name=public)
                .values_list("schema_name", flat=True)
            )
            for schema in schemas:
                # Isolate per tenant: one tenant's failure must not stop the sweep or the daemon.
                try:
                    with schema_context(schema):
                        dispatch_pending()
                except Exception:
                    logger.exception("dispatch failed for tenant %s", schema)
            if options["once"]:
                break
            time.sleep(options["interval"])
