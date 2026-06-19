"""Habit CRUD + occurrence-tracking tools."""

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

    @mcp.tool()
    async def list_habit_occurrences(
        habit_id: str,
        from_date: str | None = None,
        to_date: str | None = None,
        ctx: Context = None,
    ) -> str:
        """List occurrences for a habit in a date window.

        ``habit_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the lookup.

        Dates use YYYY-MM-DD; range is inclusive on both ends.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                habit_id = await resolve_ref(client, habit_id)
                occurrences = await client.list_habit_occurrences(
                    habit_id, from_date=from_date, to_date=to_date
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(occurrences)

    @mcp.tool()
    async def mark_habit_occurrence(
        habit_id: str,
        done: bool,
        date: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Mark a habit occurrence as done or not-done.

        ``habit_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before marking the occurrence.

        ``date`` is YYYY-MM-DD; defaults to today on the server side.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                habit_id = await resolve_ref(client, habit_id)
                occurrence = await client.mark_habit_occurrence(
                    habit_id, done, date=date
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(occurrence)

    @mcp.tool()
    async def clear_habit_occurrence(
        habit_id: str,
        date: str,
        ctx: Context = None,
    ) -> str:
        """Clear an explicitly-marked habit occurrence at ``date`` (YYYY-MM-DD).

        ``habit_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before clearing the occurrence.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                habit_id = await resolve_ref(client, habit_id)
                await client.clear_habit_occurrence(habit_id, date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"cleared": True, "habit_id": habit_id, "date": date})

    @mcp.tool()
    async def reschedule_habit_occurrence(
        habit_id: str,
        date: str,
        new_date: str,
        ctx: Context = None,
    ) -> str:
        """Move a single habit occurrence to ``new_date`` without touching the cadence.

        ``habit_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the reschedule. ``date`` and
        ``new_date`` are YYYY-MM-DD occurrence dates, not item references.

        NOTE (v0.2): the backend returns 501 today for habits (legacy
        storage); the tool is exposed for forward compatibility.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                habit_id = await resolve_ref(client, habit_id)
                occ = await client.reschedule_habit_occurrence(habit_id, date, new_date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(occ)
