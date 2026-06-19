"""Tool registration modules for the Deferno MCP server."""

from .auth import register as register_auth
from .chores import register as register_chores
from .comments import register as register_comments
from .event_occurrences import register as register_event_occurrences
from .events import register as register_events
from .feedback import register as register_feedback
from .habits import register as register_habits
from .item_activity import register as register_item_activity
from .items import register as register_items
from .pinned import register as register_pinned
from .saved_searches import register as register_saved_searches
from .tasks import register as register_tasks
from .daily_plan import register as register_daily_plan

__all__ = [
    "register_auth",
    "register_chores",
    "register_comments",
    "register_event_occurrences",
    "register_events",
    "register_feedback",
    "register_habits",
    "register_item_activity",
    "register_items",
    "register_pinned",
    "register_saved_searches",
    "register_tasks",
    "register_daily_plan",
]
