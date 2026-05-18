"""MCP tools for per-Task attachments (PR-F).

The flow is two-step: presign returns one PUT URL per file in the batch;
the caller PUTs each blob, then calls commit with the returned
attachment_ids (plus optionally any url-provider entries that need no
upload). list / delete are the usual read + GC operations.
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
    async def presign_task_attachments(
        task_id: str,
        files: list[dict],
        ctx: Context = None,
    ) -> str:
        """Batch-presign S3 PUT URLs for files to attach to a task.

        ``files`` is a list of ``{filename, content_type, size_bytes}``
        records (the wire keys match the backend ``PresignRequest`` struct
        — no serde renames). The server enforces a 25 MB per-file cap and
        a blocked-MIME list; violations return 400. Returns a list of
        ``{attachment_id, put_url, expires_at}`` records — the caller
        PUTs each blob to its url before invoking ``commit_task_attachments``.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                resp = await client.presign_task_attachments(task_id, files)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def commit_task_attachments(
        task_id: str,
        intents: list[str] | None = None,
        urls: list[dict] | None = None,
        ctx: Context = None,
    ) -> str:
        """Commit presigned intents and/or url-provider entries to a task.

        ``intents`` is a list of attachment_ids returned by a prior
        presign call. ``urls`` is a list of ``{url, filename?}`` records
        for the url-provider (no upload). At least one must be non-empty.
        Returns the full attachments Vec post-commit.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                resp = await client.commit_task_attachments(task_id, intents, urls)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def list_task_attachments(task_id: str, ctx: Context = None) -> str:
        """List a task's attachments. Returns the AttachmentView wire shape:
        ``{id, provider, filename, mime, size, created_at, created_by, url}``.
        For ``provider=s3`` records, ``url`` is a freshly-signed GET URL.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                resp = await client.list_task_attachments(task_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def delete_task_attachment(
        task_id: str,
        att_id: str,
        ctx: Context = None,
    ) -> str:
        """Delete a single attachment from a task."""
        async with (await get_client(ctx=ctx)) as client:
            try:
                await client.delete_task_attachment(task_id, att_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"ok": True})
