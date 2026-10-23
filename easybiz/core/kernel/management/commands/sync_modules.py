from django.core.management.base import BaseCommand

from easybiz.core.kernel import lifecycle


class Command(BaseCommand):
    """Record every module found on disk, and core permissions, in the catalog."""

    def handle(self, *args, **options) -> None:
        order = lifecycle.sync_catalog()
        self.stdout.write(f"synced: {', '.join(order)}")
