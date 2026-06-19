"""Habit CRUD tools. Occurrence ops are the kind-neutral occurrence tools."""

from __future__ import annotations

import json
from typing import Annotated, Any, Awaitable, Callable

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from ..client import DefernoClient, DefernoError
from ..constraints import RECURRENCE_END_DESC
from ..refs import resolve_ref


def register(
    mcp: FastMCP,
    get_client: Callable[..., Awaitable[DefernoClient]],
    format_error: Callable[[DefernoError], str],
    compact: Callable[[dict[str, Any]], dict[str, Any]],
    unset: object,
) -> None:
    @mcp.tool()
    async def update_habit(
        habit_id: str,
        title: str | None = unset,
        description: str | None = unset,
        complete_by: str | None = unset,
        recurrence: Annotated[
            dict[str, Any] | None, Field(description=RECURRENCE_END_DESC)
        ] = unset,
        labels: list[str] | None = unset,
        ctx: Context = None,
    ) -> str:
        """Patch mutable fields on a habit. Omitted fields stay untouched.

        ``habit_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the patch.

        If ``recurrence`` carries an ``end`` of ``{type: on_date, date}``, that
        date must be on or after the series start (``complete_by``'s local
        calendar date); same-day is allowed.

        v0.2 optional fields:
        - ``deadline_time_of_day``: ``"HH:MM"`` time-of-day deadline (user's TZ).
        - ``subtask_template``: list of subtask shapes materialized per occurrence.
        """
        payload = compact({
            "title": title,
            "description": description,
            "complete_by": complete_by,
            "recurrence": recurrence,
            "labels": labels,
        })
        async with (await get_client(ctx=ctx)) as client:
            try:
                habit_id = await resolve_ref(client, habit_id)
                habit = await client.update_habit(habit_id, payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(habit)

    @mcp.tool()
    async def delete_habit(habit_id: str, ctx: Context = None) -> str:
        """Archive (soft-delete) a habit.

        ``habit_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the delete.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                habit_id = await resolve_ref(client, habit_id)
                await client.delete_habit(habit_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"deleted": True, "habit_id": habit_id})
