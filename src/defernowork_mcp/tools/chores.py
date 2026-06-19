"""Chore CRUD + occurrence-tracking tools."""

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
    async def update_chore(
        chore_id: str,
        title: str | None = unset,
        description: str | None = unset,
        complete_by: str | None = unset,
        recurrence: Annotated[
            dict[str, Any] | None, Field(description=RECURRENCE_END_DESC)
        ] = unset,
        labels: list[str] | None = unset,
        ctx: Context = None,
    ) -> str:
        """Patch mutable fields on a chore. Omitted fields stay untouched.

        ``chore_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the patch.

        ``complete_by`` cannot be cleared on chores. Pass new value to shift
        the schedule. Updating ``recurrence`` rotates the chore's series ID
        so prior occurrences remain attached to the old definition. If
        ``recurrence`` carries an ``end`` of ``{type: on_date, date}``, that
        date must be on or after the series start (``complete_by``'s local
        calendar date); same-day is allowed.

        v0.2 optional fields:
        - ``cadence_mode``: ``"rolling"`` (default; the next occurrence is
          computed from the actual completion time) or ``"fixed"`` (the next
          occurrence is anchored to the original schedule, ignoring completion
          delay).
        - ``deadline_time_of_day``: ``"HH:MM"`` time-of-day deadline within
          ``scheduled_date`` (user's TZ). Defaults to end-of-day.
        - ``subtask_template``: a list of subtask shapes that materialize as
          child Tasks on each occurrence. Empty list (default) means no template.
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
                chore_id = await resolve_ref(client, chore_id)
                chore = await client.update_chore(chore_id, payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(chore)

    @mcp.tool()
    async def delete_chore(chore_id: str, ctx: Context = None) -> str:
        """Archive (soft-delete) a chore.

        ``chore_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the delete.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                chore_id = await resolve_ref(client, chore_id)
                await client.delete_chore(chore_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"deleted": True, "chore_id": chore_id})

    @mcp.tool()
    async def mark_next_chore_done(
        chore_id: str,
        status: str = "done",
        ctx: Context = None,
    ) -> str:
        """Apply ``status`` to the earliest unresolved occurrence of a chore.

        ``chore_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before marking the occurrence.

        Useful for the common "I just did the dishes" case where the user
        doesn't want to look up which date is overdue. 404 if no
        unresolved occurrence exists.

        ``status`` is the action to apply: one of ``"in_progress"``,
        ``"done"``, or ``"dropped"`` (alias: ``"skipped"`` for legacy
        callers).

        Note: ``Done`` resolves on the server to either ``DoneOnTime``
        or ``DoneLate`` based on the occurrence's ``complete_by``.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                chore_id = await resolve_ref(client, chore_id)
                occurrence = await client.mark_next_chore_done(chore_id, status=status)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(occurrence)
