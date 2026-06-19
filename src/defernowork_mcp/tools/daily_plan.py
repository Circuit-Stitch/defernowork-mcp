"""Daily plan tool: today's curated, server-seeded plan view.

Plan mutations and the calendar view are the kind-neutral item tools
(``add_to_items_plan`` / ``remove_from_items_plan`` / ``reorder_items_plan`` /
``get_items_calendar``): ``/items/plan/*`` and ``/items/calendar`` are the SAME
backend handlers as the retired ``/tasks/plan/*`` and ``/tasks/calendar`` ones,
so the task-scoped duplicates were dropped. ``get_daily_plan`` stays — it is the
seeded Task-view today-read (auto-seeded server-side on the read path,
independent of the plan-mutation endpoints).
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from mcp.server.fastmcp import Context, FastMCP

from ..client import DefernoClient, DefernoError


def register(
    mcp: FastMCP,
    get_client: Callable[..., Awaitable[DefernoClient]],
    format_error: Callable[[DefernoError], str],
) -> None:
    @mcp.tool()
    async def get_daily_plan(
        date: str | None = None,
        tz: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Return today's curated daily plan.

        The plan auto-seeds from recurring tasks, carries forward incomplete
        items from yesterday, and includes any task/chore/event with a due
        date falling on the target date in the user's timezone.

        Parameters
        ----------
        date : optional YYYY-MM-DD. Defaults to today *in the user's
            timezone*. If no timezone is known, defaults to UTC.
        tz : optional IANA timezone (e.g. "America/Los_Angeles"). Supply
            if you know the user's local timezone — Claude Desktop /
            Claude Code typically have this in the system prompt as
            locale info. Once supplied for the first time, the backend
            persists it as the user's preference, so future calls don't
            need to repeat it.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                plan = await client.get_daily_plan(date, tz=tz)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(plan)
