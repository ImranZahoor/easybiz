from django.core.management.base import BaseCommand

from easybiz.core.kernel import lifecycle


class Command(BaseCommand):
    """Refresh the catalog, migrate every schema, and record module versions."""

    def handle(self, *args, **options) -> None:
        order = lifecycle.upgrade_modules()
        self.stdout.write(f"upgraded: {', '.join(order)}")
