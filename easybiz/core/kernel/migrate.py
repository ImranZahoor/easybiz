from __future__ import annotations

from django.conf import settings
from django.core.management.commands.migrate import Command as MigrateCommand
from django.db import connection
from django.test.utils import override_settings
from django_tenants.utils import get_public_schema_name

from easybiz.core.kernel.registry import registry
from easybiz.core.kernel.routers import module_has_tables


class Command(MigrateCommand):
    """Per-schema migrate that hides modules a tenant schema lacks, so Django records no
    migration state for them there (closes pitfall P2).

    On the public schema modules are NOT hidden: the router still keeps their tables out of
    public, but their migrations get no-op-recorded (like the core tenant apps), so a stock
    ``runserver`` migration check does not report them as unapplied. Public never enables a
    module, and ``django_migrations`` is per-schema, so this cannot affect a tenant's enable.
    """

    def handle(self, *args, **options):
        schema = getattr(connection, "schema_name", None) or get_public_schema_name()
        public = schema == get_public_schema_name()
        hidden = {
            module_id: None
            for module_id in registry.module_ids()
            if not public and not module_has_tables(schema, module_id)
        }
        existing = getattr(settings, "MIGRATION_MODULES", {})
        with override_settings(MIGRATION_MODULES={**existing, **hidden}):
            super().handle(*args, **options)
