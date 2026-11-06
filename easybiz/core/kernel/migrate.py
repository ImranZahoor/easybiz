from __future__ import annotations

from django.conf import settings
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import connection
from django.test.utils import override_settings
from django_tenants.utils import get_public_schema_name

from easybiz.core.kernel.registry import registry
from easybiz.core.kernel.routers import module_has_tables


class Command(MigrateCommand):
    """Migrate one schema, skipping modules it hasn't installed.

    A tenant gets a module's tables only once it enables the module. Until then we hide that
    module's migrations, or Django would record them as done and refuse to build the tables on
    enable. Public keeps every module visible (it owns none of their tables either way) so
    ``runserver`` doesn't flag them as unapplied.
    """

    def handle(self, *args, **options):
        schema = getattr(connection, "schema_name", None) or get_public_schema_name()
        public = schema == get_public_schema_name()
        # Hide a module's migrations only in a tenant schema that doesn't have its tables yet.
        hidden = {
            module_id: None
            for module_id in registry.module_ids()
            if not public and not module_has_tables(schema, module_id)
        }
        existing = getattr(settings, "MIGRATION_MODULES", {})
        with override_settings(MIGRATION_MODULES={**existing, **hidden}):
            super().handle(*args, **options)
