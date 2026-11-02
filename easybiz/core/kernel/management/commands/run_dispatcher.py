import time

from django.core.management.base import BaseCommand
from django_tenants.utils import get_public_schema_name, schema_context

from easybiz.core.events.service import dispatch_pending
from easybiz.core.tenancy.models import Tenant


class Command(BaseCommand):
    """Deliver outbox events for every active tenant (polling; Celery is F15)."""

    def add_arguments(self, parser) -> None:
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=2)

    def handle(self, *args, **options) -> None:
        public = get_public_schema_name()
        while True:
            for schema in (
                Tenant.objects.filter(is_active=True)
                .exclude(schema_name=public)
                .values_list("schema_name", flat=True)
            ):
                with schema_context(schema):
                    dispatch_pending()
            if options["once"]:
                break
            time.sleep(options["interval"])
