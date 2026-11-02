from __future__ import annotations

from django.conf import settings
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import connection
from django.test.utils import override_settings
from django_tenants.utils import get_public_schema_name

from easybiz.core.kernel.registry import registry
from easybiz.core.kernel.routers import module_has_tables


class Command(MigrateCommand):
    """Per-schema migrate that hides modules the schema lacks, so Django records no
    migration state for them (closes pitfall P2)."""

    def handle(self, *args, **options):
        schema = getattr(connection, "schema_name", None) or get_public_schema_name()
        public = schema == get_public_schema_name()
        hidden = {
            module_id: None
            for module_id in registry.module_ids()
            if public or not module_has_tables(schema, module_id)
        }
        existing = getattr(settings, "MIGRATION_MODULES", {})
        with override_settings(MIGRATION_MODULES={**existing, **hidden}):
            super().handle(*args, **options)
