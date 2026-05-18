"""MCP tools for event occurrences (PR-D v0.2 surface).

This module wires the per-occurrence operations on Events: list, set, delete.
Subsequent gap-closure tasks add per-occurrence comments, attachments, and
the SCOPE-010 reschedule endpoint to this module.
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
    async def list_event_occurrences(
        event_id: str,
        from_date: str | None = None,
        to_date: str | None = None,
        ctx: Context = None,
    ) -> str:
        """List occurrences for an Event in a date range.

        ``from_date`` / ``to_date`` are YYYY-MM-DD; both optional. Returns
        the unified-Occurrence shape (id, parent_id, scheduled_date,
        status, comment, attachments). Events never produce ``DoneLate``.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                occs = await client.list_event_occurrences(event_id, from_date, to_date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(occs)

    @mcp.tool()
    async def set_event_occurrence(
        event_id: str,
        date: str,
        action: str,
        cascade_subtasks: bool = False,
        ctx: Context = None,
    ) -> str:
        """Mark a single event occurrence with an action.

        ``action`` is one of ``"in_progress"``, ``"done"``, ``"dropped"``
        (alias: ``"skipped"``). ``date`` is YYYY-MM-DD.

        When the occurrence has materialized subtasks, ``cascade_subtasks=false``
        (the default) causes a 409 if any subtask is non-terminal
        (SUBTASK-003). Pass ``cascade_subtasks=true`` to sweep them to
        the matching terminal status.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                occ = await client.set_event_occurrence(
                    event_id, date, action, cascade_subtasks
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(occ)

    @mcp.tool()
    async def delete_event_occurrence(
        event_id: str,
        date: str,
        ctx: Context = None,
    ) -> str:
        """Clear an event occurrence row entirely (undo a prior mark).

        ``date`` is YYYY-MM-DD. Returns ``{"ok": true}`` on success.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                await client.delete_event_occurrence(event_id, date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"ok": True})

    @mcp.tool()
    async def reschedule_event_occurrence(
        event_id: str,
        date: str,
        new_date: str,
        ctx: Context = None,
    ) -> str:
        """Move a single event occurrence to ``new_date`` without touching the RRULE.

        The origin date's row is marked ``Dropped`` (with
        ``rescheduled_to=new_date``); a fresh ``Scheduled`` row lands on
        the target date (with ``rescheduled_from=origin_date``). 400 if
        ``new_date`` equals the origin date.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                occ = await client.reschedule_event_occurrence(event_id, date, new_date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(occ)

    @mcp.tool()
    async def presign_event_occurrence_attachments(
        event_id: str,
        date: str,
        files: list[dict],
        ctx: Context = None,
    ) -> str:
        """Batch-presign attachments for a specific event occurrence (date).

        Each entry in ``files`` is ``{filename, content_type, size_bytes}``.
        Server enforces 25 MB per-file cap, blocked-MIME list, and a
        max-attachments cap. Returns presigned PUT URLs with intent ids
        that ``commit_event_occurrence_attachments`` later consumes.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                resp = await client.presign_event_occurrence_attachments(
                    event_id, date, files
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def commit_event_occurrence_attachments(
        event_id: str,
        date: str,
        intents: list[str] | None = None,
        urls: list[dict] | None = None,
        ctx: Context = None,
    ) -> str:
        """Commit intents and/or url-provider entries to an event occurrence.

        ``intents`` are attachment ids returned by a prior presign call
        whose files have been PUT to S3. ``urls`` are url-provider entries
        ``{url, filename?}``. 400 if both lists are empty.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                resp = await client.commit_event_occurrence_attachments(
                    event_id, date, intents, urls
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def list_event_occurrence_attachments(
        event_id: str,
        date: str,
        ctx: Context = None,
    ) -> str:
        """List attachments on a specific event occurrence (date).

        Returns the AttachmentView shape:
        ``{id, provider, filename, mime, size, created_at, created_by, url}``.
        ``url`` is a freshly signed GET for s3-backed entries.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                resp = await client.list_event_occurrence_attachments(event_id, date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def delete_event_occurrence_attachment(
        event_id: str,
        date: str,
        att_id: str,
        ctx: Context = None,
    ) -> str:
        """Delete a single attachment from an event occurrence.

        ``att_id`` is the attachment id returned in the AttachmentView.
        Returns ``{"ok": true}`` on success.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                await client.delete_event_occurrence_attachment(
                    event_id, date, att_id
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"ok": True})
