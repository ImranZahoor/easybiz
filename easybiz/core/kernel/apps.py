from django.apps import AppConfig


class KernelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "easybiz.core.kernel"
    label = "kernel"

    def ready(self) -> None:
        """Registry loading is wired in M2; no-op at M0."""
