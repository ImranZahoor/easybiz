from django.apps import AppConfig

from easybiz.core.kernel.registry import registry


class KernelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easybiz.core.kernel"
    label = "kernel"

    def ready(self) -> None:
        """Load and validate module manifests at startup (M2)."""
        registry.ensure_loaded()
        registry.verify_apps()
        registry.import_module_code()
