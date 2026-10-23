from django.core.management.base import BaseCommand
from django.db import transaction

from easybiz.core.tenancy.models import Domain, Tenant


class Command(BaseCommand):
    """Create the public (platform) tenant and its primary domain. Idempotent."""

    help = "Create the public tenant and its primary domain."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--domain", default="localhost")

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        tenant, created = Tenant.objects.get_or_create(
            schema_name="public",
            defaults={"slug": "platform", "name": "Platform"},
        )
        Domain.objects.get_or_create(
            domain=options["domain"],
            tenant=tenant,
            defaults={"is_primary": True},
        )

        from easybiz.core.kernel import lifecycle

        lifecycle.sync_catalog()
        self.stdout.write(
            f"public tenant {'created' if created else 'exists'}; "
            f"domain {options['domain']}; catalog synced"
        )
