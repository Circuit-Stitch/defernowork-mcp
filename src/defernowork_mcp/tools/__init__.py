"""Tool registration modules for the Deferno MCP server."""

from .auth import register as register_auth
from .capture import register as register_capture
from .comments import register as register_comments
from .event_occurrences import register as register_event_occurrences
from .item_activity import register as register_item_activity
from .items import register as register_items
from .occurrences import register as register_occurrences
from .tasks import register as register_tasks
from .daily_plan import register as register_daily_plan

__all__ = [
    "register_auth",
    "register_capture",
    "register_comments",
    "register_event_occurrences",
    "register_item_activity",
    "register_items",
    "register_occurrences",
    "register_tasks",
    "register_daily_plan",
]
