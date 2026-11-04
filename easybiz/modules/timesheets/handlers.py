from easybiz.core.kernel.registry import subscribe
from easybiz.modules.timesheets import commands


@subscribe("core.membership.removed")
def drop_draft_entries(event):
    """Delete a removed member's draft time; submitted/approved/rejected is kept."""
    commands.drop_user_drafts(event["payload"]["user_id"])
