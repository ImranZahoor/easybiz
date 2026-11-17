from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from easybiz.core.kernel import scaffold


class Command(BaseCommand):
    help = "Scaffold a new module (worked-sample, contract-clean) under the module path."

    def add_arguments(self, parser):
        parser.add_argument("module_id")
        parser.add_argument("--requires", nargs="*", default=[])
        parser.add_argument("--optional", nargs="*", default=[])
        parser.add_argument("--path", default="easybiz.modules", help="dotted package root")

    def handle(self, *args, **options):
        module_id = options["module_id"]
        package_root = options["path"]
        base_dir = Path(settings.BASE_DIR, *package_root.split("."))
        try:
            dest = scaffold.scaffold_module(
                module_id,
                base_dir=base_dir,
                package_root=package_root,
                requires=options["requires"],
                optional=options["optional"],
            )
        except (ValueError, FileExistsError) as exc:
            raise CommandError(str(exc)) from exc

        package = f"{package_root}.{module_id}"
        if not scaffold.add_to_env(package, Path(settings.BASE_DIR, ".env")):
            self.stdout.write(f"Add to EASYBIZ_MODULES manually: {package}")
        self.stdout.write(self.style.SUCCESS(f"created {dest}"))
        self.stdout.write(
            f"Next: restart the process, run `manage.py sync_modules`, "
            f"then `manage.py check_module {module_id}`."
        )
