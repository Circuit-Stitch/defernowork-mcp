"""MCP tools for Event-occurrence comments + attachments (PR-F surface).

Event-occurrence *status* (list / set / reschedule) is handled by the
kind-neutral occurrence tools (tools/occurrences.py). This module wires the
Event-only per-occurrence comment and attachment operations, which have no
kind-neutral equivalent: an Event occurrence is addressed by ``event_id`` +
``date``, and only Events expose occurrence-scoped comments/attachments.
"""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from mcp.server.fastmcp import Context, FastMCP

from ..client import DefernoClient, DefernoError
from ..refs import resolve_ref


def register(
    mcp: FastMCP,
    get_client: Callable[..., Awaitable[DefernoClient]],
    format_error: Callable[[DefernoError], str],
) -> None:
    @mcp.tool()
    async def presign_event_occurrence_attachments(
        event_id: str,
        date: str,
        files: list[dict],
        ctx: Context = None,
    ) -> str:
        """Batch-presign attachments for a specific event occurrence (date).

        ``event_id`` accepts any item ref.

        Each entry in ``files`` is ``{filename, content_type, size_bytes}``.
        Server enforces 25 MB per-file cap, blocked-MIME list, and a
        max-attachments cap. Returns presigned PUT URLs with intent ids
        that ``commit_event_occurrence_attachments`` later consumes.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                event_id = await resolve_ref(client, event_id)
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

        ``event_id`` accepts any item ref.

        ``intents`` are attachment ids returned by a prior presign call
        whose files have been PUT to S3. ``urls`` are url-provider entries
        ``{url, filename?}``. 400 if both lists are empty.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                event_id = await resolve_ref(client, event_id)
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

        ``event_id`` accepts any item ref.

        Returns the AttachmentView shape:
        ``{id, provider, filename, mime, size, created_at, created_by, url}``.
        ``url`` is a freshly signed GET for s3-backed entries.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                event_id = await resolve_ref(client, event_id)
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

        ``event_id`` accepts any item ref. ``att_id`` is the
        attachment id returned in the AttachmentView (not an item reference)
        and is passed through unresolved.

        Returns ``{"ok": true}`` on success.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                event_id = await resolve_ref(client, event_id)
                await client.delete_event_occurrence_attachment(
                    event_id, date, att_id
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"ok": True})

    @mcp.tool()
    async def post_event_occurrence_comment(
        event_id: str,
        date: str,
        body: str,
        is_private: bool = False,
        ctx: Context = None,
    ) -> str:
        """Append a new comment to an event occurrence (date).

        ``event_id`` accepts any item ref.

        Multiple comments per occurrence are supported (PR-F). Returns
        the persisted Comment with id + created_at.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                event_id = await resolve_ref(client, event_id)
                resp = await client.post_event_occurrence_comment(
                    event_id, date, body, is_private
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def patch_event_occurrence_comment(
        event_id: str,
        date: str,
        body: str | None = None,
        is_private: bool | None = None,
        ctx: Context = None,
    ) -> str:
        """Edit the latest comment on an event occurrence (date).

        ``event_id`` accepts any item ref.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                event_id = await resolve_ref(client, event_id)
                resp = await client.patch_event_occurrence_comment(
                    event_id, date, body, is_private
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def delete_event_occurrence_comment(
        event_id: str,
        date: str,
        ctx: Context = None,
    ) -> str:
        """Soft-delete the latest comment on an event occurrence (date).

        ``event_id`` accepts any item ref.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                event_id = await resolve_ref(client, event_id)
                await client.delete_event_occurrence_comment(event_id, date)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"ok": True})
