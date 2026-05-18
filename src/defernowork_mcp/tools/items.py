"""Cross-kind item tools: calendar + plan over Tasks/Habits/Chores/Events."""

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
    async def get_items_calendar(
        start: str,
        end: str,
        tz: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Calendar view across all item kinds (Task, Habit, Chore, Event).

        ``start`` and ``end`` are YYYY-MM-DD; ``end`` is exclusive.
        ``tz`` is an optional IANA timezone for local-midnight alignment.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                items = await client.get_items_calendar(start, end, tz=tz)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(items)

    @mcp.tool()
    async def get_items_plan(
        date: str | None = None,
        tz: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Daily plan across all item kinds (Task, Habit, Chore, Event).

        Returns a polymorphic array — each entry has a ``kind`` discriminator.
        ``date`` defaults to today; ``tz`` is an optional IANA timezone.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                items = await client.get_items_plan(date=date, tz=tz)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(items)

    @mcp.tool()
    async def add_to_items_plan(
        task_id: str,
        date: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Add an item (any kind) to the daily plan."""
        async with (await get_client(ctx=ctx)) as client:
            try:
                result = await client.add_to_items_plan(task_id, date=date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)

    @mcp.tool()
    async def remove_from_items_plan(
        task_id: str,
        date: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Remove an item from the daily plan."""
        async with (await get_client(ctx=ctx)) as client:
            try:
                result = await client.remove_from_items_plan(task_id, date=date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)

    @mcp.tool()
    async def reorder_items_plan(
        task_ids: list[str],
        date: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Replace the daily plan ordering with the given full list of IDs."""
        async with (await get_client(ctx=ctx)) as client:
            try:
                result = await client.reorder_items_plan(task_ids, date=date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)

    @mcp.tool()
    async def convert_item(
        item_id: str,
        to: str,
        complete_by: str | None = None,
        end_time: str | None = None,
        recurrence: dict | None = None,
        ctx: Context = None,
    ) -> str:
        """Convert an item to a different kind (Task / Chore / Habit / Event).

        ``to`` is one of ``"task"``, ``"chore"``, ``"habit"``, ``"event"`` --
        this is the backend wire field name (``ConvertItemPayload.to``).
        ``complete_by`` (RFC3339) is required when ``to`` is Event/Chore/Habit;
        ``recurrence`` is required when ``to`` is Habit/Chore (and optional for
        Event); ``end_time`` is Event-only. Returns the updated item view --
        the backend uses 201 on a real conversion, 200 when ``to`` equals the
        current kind (idempotent).
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                resp = await client.convert_item(
                    item_id,
                    to,
                    complete_by=complete_by,
                    end_time=end_time,
                    recurrence=recurrence,
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def get_item_history(item_id: str, ctx: Context = None) -> str:
        """Return the change-history list for any item kind (Task/Habit/Chore/Event)."""
        async with (await get_client(ctx=ctx)) as client:
            try:
                resp = await client.get_item_history(item_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def set_item_pinned(
        item_id: str,
        pinned: bool,
        ctx: Context = None,
    ) -> str:
        """Pin or unpin a sidebar item (Task/Habit/Chore/Event).

        Backend body is ``{pinned: bool}`` -- the gap-closure plan's optional
        ``label`` argument is not part of this endpoint (custom pin labels
        live on ``PATCH /tasks/pinned/{id}``). Returns ``{"ok": true}`` on
        success (backend response is 204 NO_CONTENT).
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                await client.set_item_pinned(item_id, pinned)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"ok": True})
