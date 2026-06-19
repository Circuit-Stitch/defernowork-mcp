"""Kind-neutral item-level comment + attachment tools (issue #12).

The per-kind tools (``post_event_occurrence_comment``, ``*_task_attachments``,
…) require the caller to know an item's kind and address an occurrence. These
tools are the *kind-neutral* surface: comment on / attach to a **Task, Chore,
or Habit** by any reference form, hitting ``/items/{id}/...``. The caller never
addresses occurrences — for recurring kinds the backend routes the write to the
current actionable occurrence and aggregates reads into the item-level Activity
timeline (see Deferno ADR occurrence-comments-storage-vs-presentation).

**Events are NOT supported here.** An Event has no unambiguous item-level
target, so the backend rejects an item-level comment/attachment on an Event with
a 400 — use the per-occurrence tools instead (``post_event_occurrence_comment``,
``presign_event_occurrence_attachments`` / ``commit_…`` / ``list_…`` /
``delete_…``).

Status: the ``/items/{id}/comments`` path is live for Task and extends to
Chore/Habit with Deferno backend #266; the ``/items/{id}/attachments/*`` paths
land with #215. Until those ship, the Chore/Habit/attachment paths cannot be
verified end-to-end (the MCP wiring + ref resolution are exercised against the
mocked contract in tests/test_item_comments.py and tests/test_item_attachments.py).
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
    async def post_item_comment(
        item_id: str,
        body: str,
        is_private: bool = False,
        ctx: Context = None,
    ) -> str:
        """Append a comment to an item by reference (kind-neutral).

        Works for **Task, Chore, and Habit**. **Not for Events** — the backend
        rejects an Event here with a 400; use ``post_event_occurrence_comment``.

        ``item_id`` accepts any item ref (UUID / ``#123`` / ``acme-123`` / app URL; see instructions).

        For a recurring Chore/Habit the comment is routed server-side to the
        current actionable occurrence; the caller does not address occurrences.
        ``is_private`` keeps the comment visible only to its author. Returns the
        persisted comment (id + created_at).
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                item_id = await resolve_ref(client, item_id)
                comment = await client.post_item_comment(item_id, body, is_private)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(comment)

    @mcp.tool()
    async def list_item_comments(item_id: str, ctx: Context = None) -> str:
        """List an item's comments by reference (kind-neutral).

        ``item_id`` accepts any item ref (UUID / ``#123`` / ``acme-123`` / app URL; see instructions).

        Returns the aggregated item-level Activity timeline. For a recurring
        Chore/Habit, entries from every occurrence are folded in (each tagged
        with its occurrence date); for a Task it is simply the task's comments.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                item_id = await resolve_ref(client, item_id)
                comments = await client.list_item_comments(item_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(comments)

    @mcp.tool()
    async def presign_item_attachments(
        item_id: str,
        files: list[dict],
        ctx: Context = None,
    ) -> str:
        """Batch-presign attachment upload URLs for an item (kind-neutral).

        Works for **Task, Chore, and Habit**. **Not for Events** — the backend
        rejects an Event here with a 400; use the per-occurrence Event tools.

        ``item_id`` accepts any item ref (UUID / ``#123`` / ``acme-123`` / app URL; see instructions).

        ``files`` is a list of ``{filename, content_type, size_bytes}`` records.
        The server enforces a 25 MB per-file cap and a blocked-MIME list.
        Returns ``{attachment_id, put_url, expires_at}`` records — PUT each blob
        to its url, then call ``commit_item_attachments``.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                item_id = await resolve_ref(client, item_id)
                resp = await client.presign_item_attachments(item_id, files)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def commit_item_attachments(
        item_id: str,
        intents: list[str] | None = None,
        urls: list[dict] | None = None,
        ctx: Context = None,
    ) -> str:
        """Commit presigned intents and/or url-provider entries to an item.

        Works for **Task, Chore, and Habit**. **Not for Events** — the backend
        rejects an Event here with a 400; use the per-occurrence Event tools.

        ``item_id`` accepts any item ref (UUID / ``#123`` / ``acme-123`` / app URL; see instructions).

        ``intents`` is a list of attachment_ids from a prior presign call whose
        blobs have been PUT. ``urls`` is a list of ``{url, filename?}`` entries
        for the url provider (no upload). At least one must be non-empty.
        Returns the item's full attachments list post-commit.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                item_id = await resolve_ref(client, item_id)
                resp = await client.commit_item_attachments(item_id, intents, urls)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def list_item_attachments(item_id: str, ctx: Context = None) -> str:
        """List an item's attachments by reference (kind-neutral).

        ``item_id`` accepts any item ref (UUID / ``#123`` / ``acme-123`` / app URL; see instructions).

        Returns the AttachmentView shape
        ``{id, provider, filename, mime, size, created_at, created_by, url,
        caption, caption_updated_at, caption_updated_by}``. For ``provider=s3``
        records, ``url`` is a freshly-signed GET URL.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                item_id = await resolve_ref(client, item_id)
                resp = await client.list_item_attachments(item_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)

    @mcp.tool()
    async def delete_item_attachment(
        item_id: str,
        att_id: str,
        ctx: Context = None,
    ) -> str:
        """Delete a single attachment from an item (kind-neutral).

        ``item_id`` accepts any item ref (UUID / ``#123`` / ``acme-123`` / app URL; see instructions). ``att_id`` is an attachment
        id (not an item reference) and is passed through unresolved.

        Returns ``{"ok": true}`` on success.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                item_id = await resolve_ref(client, item_id)
                await client.delete_item_attachment(item_id, att_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"ok": True})

    @mcp.tool()
    async def set_item_attachment_caption(
        item_id: str,
        att_id: str,
        caption: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Set or clear an item attachment's caption (kind-neutral).

        ``item_id`` accepts any item ref (UUID / ``#123`` / ``acme-123`` / app URL; see instructions). ``att_id`` is an attachment
        id (not an item reference) and is passed through unresolved.

        Pass a string to set/change the caption (max 500 characters), or
        ``caption=None`` (the default) to clear it — an empty string ``""`` is
        rejected by the backend with a 400, so ``null`` is the only clear.
        Returns the updated AttachmentView.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                item_id = await resolve_ref(client, item_id)
                resp = await client.set_item_attachment_caption(
                    item_id, att_id, caption
                )
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(resp)
