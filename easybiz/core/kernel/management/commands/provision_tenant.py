from django.core.management.base import BaseCommand, CommandError

from easybiz.core.kernel import provisioning
from easybiz.core.kernel.tenants import TenantError


class Command(BaseCommand):
    """Create a tenant end to end."""

    def add_arguments(self, parser) -> None:
        parser.add_argument("slug")
        parser.add_argument("--domain", required=True)
        parser.add_argument("--owner-email", required=True)
        parser.add_argument("--owner-password")
        parser.add_argument("--name")
        parser.add_argument("--modules", default="")

    def handle(self, *args, **options) -> None:
        modules = tuple(m for m in options["modules"].split(",") if m)
        try:
            tenant = provisioning.provision_tenant(
                name=options["name"] or options["slug"].title(),
                slug=options["slug"],
                domain=options["domain"],
                owner_email=options["owner_email"],
                owner_password=options["owner_password"],
                modules=modules,
            )
        except TenantError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"provisioned tenant {tenant.slug!r} ({tenant.schema_name})")
