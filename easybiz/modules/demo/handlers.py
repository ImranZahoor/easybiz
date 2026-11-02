from easybiz.core.kernel.registry import subscribe
from easybiz.modules.demo.models import Widget


@subscribe("core.module.enabled")
def record_enabled(event):
    """Record a widget whenever a module is enabled (demo event handler)."""
    Widget.objects.create(name=event["payload"]["module"])
