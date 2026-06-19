"""Tool registration modules for the Deferno MCP server."""

from .auth import register as register_auth
from .capture import register as register_capture
from .chores import register as register_chores
from .comments import register as register_comments
from .event_occurrences import register as register_event_occurrences
from .feedback import register as register_feedback
from .item_activity import register as register_item_activity
from .items import register as register_items
from .occurrences import register as register_occurrences
from .pinned import register as register_pinned
from .saved_searches import register as register_saved_searches
from .tasks import register as register_tasks
from .daily_plan import register as register_daily_plan

__all__ = [
    "register_auth",
    "register_capture",
    "register_chores",
    "register_comments",
    "register_event_occurrences",
    "register_feedback",
    "register_item_activity",
    "register_items",
    "register_occurrences",
    "register_pinned",
    "register_saved_searches",
    "register_tasks",
    "register_daily_plan",
]
