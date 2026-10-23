from django.core.management.base import BaseCommand, CommandError

from easybiz.core.kernel import lifecycle
from easybiz.core.tenancy.models import Tenant

_ACTIONS = {
    "enable": lifecycle.enable_module,
    "disable": lifecycle.disable_module,
    "remove": lifecycle.remove_module_data,
}


class Command(BaseCommand):
    """Per-tenant module lifecycle from the CLI."""

    def add_arguments(self, parser) -> None:
        parser.add_argument("slug")
        parser.add_argument("action", choices=sorted(_ACTIONS))
        parser.add_argument("module")

    def handle(self, *args, **options) -> None:
        tenant = Tenant.objects.filter(slug=options["slug"]).first()
        if tenant is None:
            raise CommandError(f"no tenant with slug {options['slug']!r}")
        try:
            _ACTIONS[options["action"]](tenant, options["module"])
        except lifecycle.LifecycleError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"{options['action']} {options['module']} for {options['slug']}: ok")
