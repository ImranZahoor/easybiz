from django.core.management.base import BaseCommand, CommandError

from easybiz.core.testing import run_module_contract_checks


class Command(BaseCommand):
    help = "Run the module contract-kit checks for a module; nonzero exit on any failure."

    def add_arguments(self, parser):
        parser.add_argument("module_id")

    def handle(self, *args, **options):
        module_id = options["module_id"]
        failures = run_module_contract_checks(module_id)
        if failures:
            for failure in failures:
                self.stdout.write(self.style.ERROR(failure))
            raise CommandError(f"{module_id}: {len(failures)} contract check failure(s)")
        self.stdout.write(self.style.SUCCESS(f"{module_id}: all contract checks passed"))
