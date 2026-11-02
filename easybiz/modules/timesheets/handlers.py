from easybiz.core.kernel.registry import subscribe
from easybiz.modules.timesheets.models import Entry


@subscribe("core.membership.removed")
def drop_draft_entries(event):
    """Delete a removed member's draft time; submitted/approved/rejected is kept."""
    Entry.objects.filter(user_id=event["payload"]["user_id"], status=Entry.DRAFT).delete()
