from django.core.management.commands.migrate import Command as MigrateCommand


class Command(MigrateCommand):
    """Per-schema module-hiding is added in M3; base migrate at M0."""
