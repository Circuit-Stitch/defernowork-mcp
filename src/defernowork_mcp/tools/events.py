"""Event CRUD tools."""

from __future__ import annotations

import json
from typing import Annotated, Any, Awaitable, Callable

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from ..client import DefernoClient, DefernoError
from ..constraints import RECURRENCE_END_DESC
from ..refs import resolve_ref

# Reaffirmed on the parameter schema AND the docstring (issue #13): the backend
# rejects an event whose end precedes its start with a 400.
EVENT_END_TIME_DESC = (
    "Event end (ISO-8601). When provided, `end_time` must be on or after "
    "`complete_by` (the event's start); the backend rejects it with a 400 "
    "otherwise."
)


def register(
    mcp: FastMCP,
    get_client: Callable[..., Awaitable[DefernoClient]],
    format_error: Callable[[DefernoError], str],
    compact: Callable[[dict[str, Any]], dict[str, Any]],
    unset: object,
) -> None:
    @mcp.tool()
    async def create_event(
        title: str,
        complete_by: str,
        end_time: Annotated[str | None, Field(description=EVENT_END_TIME_DESC)] = unset,
        description: str | None = unset,
        labels: list[str] | None = unset,
        parent_id: str | None = unset,
        recurrence: Annotated[
            dict[str, Any] | None, Field(description=RECURRENCE_END_DESC)
        ] = unset,
        ctx: Context = None,
    ) -> str:
        """Create a time-bound event.

        ``complete_by`` is the start time (ISO-8601). When provided, ``end_time``
        must be on or after ``complete_by`` — the backend rejects an earlier end
        with a 400.

        If ``recurrence`` carries an ``end`` of ``{type: on_date, date}``, that
        date must be on or after the series start (``complete_by``'s local
        calendar date); same-day is allowed.

        ``parent_id`` accepts any reference form (UUID, ``#123``, ``acme-123``,
        or app URL) and is resolved to a UUID before the create.

        v0.2 optional fields:
        - ``subtask_template``: list of subtask shapes materialized per occurrence.
        """
        payload = compact({
            "title": title,
            "complete_by": complete_by,
            "end_time": end_time,
            "description": description,
            "labels": labels,
            "parent_id": parent_id,
            "recurrence": recurrence,
        })
        async with (await get_client(ctx=ctx)) as client:
            try:
                if parent_id is not unset and parent_id is not None:
                    payload["parent_id"] = await resolve_ref(client, parent_id)
                event = await client.create_event(payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(event)

    @mcp.tool()
    async def update_event(
        event_id: str,
        title: str | None = unset,
        complete_by: str | None = unset,
        end_time: Annotated[str | None, Field(description=EVENT_END_TIME_DESC)] = unset,
        description: str | None = unset,
        labels: list[str] | None = unset,
        recurrence: Annotated[
            dict[str, Any] | None, Field(description=RECURRENCE_END_DESC)
        ] = unset,
        ctx: Context = None,
    ) -> str:
        """Patch mutable fields on an event.

        When provided, ``end_time`` must be on or after ``complete_by`` — the
        backend rejects an earlier end with a 400.

        If ``recurrence`` carries an ``end`` of ``{type: on_date, date}``, that
        date must be on or after the series start (``complete_by``'s local
        calendar date); same-day is allowed.

        ``event_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the patch.

        v0.2 optional fields:
        - ``subtask_template``: list of subtask shapes materialized per occurrence.
        """
        payload = compact({
            "title": title,
            "complete_by": complete_by,
            "end_time": end_time,
            "description": description,
            "labels": labels,
            "recurrence": recurrence,
        })
        async with (await get_client(ctx=ctx)) as client:
            try:
                event_id = await resolve_ref(client, event_id)
                event = await client.update_event(event_id, payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(event)

    @mcp.tool()
    async def delete_event(event_id: str, ctx: Context = None) -> str:
        """Archive (soft-delete) an event.

        ``event_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the delete.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                event_id = await resolve_ref(client, event_id)
                await client.delete_event(event_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"deleted": True, "event_id": event_id})
