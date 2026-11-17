from django.core.management.base import BaseCommand, CommandError

from easybiz.core.kernel import lifecycle


class Command(BaseCommand):
    help = "Remove a module from the catalog (refused while any tenant still has it installed)."

    def add_arguments(self, parser):
        parser.add_argument("module_id")

    def handle(self, *args, **options):
        module_id = options["module_id"]
        try:
            lifecycle.uninstall_module(module_id)
        except lifecycle.LifecycleError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"uninstalled {module_id}"))
