"""Cross-kind item tools: calendar + plan over Tasks/Habits/Chores/Events."""

from __future__ import annotations

import json
from typing import Awaitable, Callable

from mcp.server.fastmcp import Context, FastMCP

from ..client import DefernoClient, DefernoError
from ..refs import (
    COMPACT_ITEM_CORE_FIELDS,
    COMPACT_ITEM_FIELDS,
    project,
    resolve_ref,
)


def register(
    mcp: FastMCP,
    get_client: Callable[..., Awaitable[DefernoClient]],
    format_error: Callable[[DefernoError], str],
) -> None:
    @mcp.tool()
    async def get_item(
        item: str,
        full: bool = False,
        as_alias: bool = False,
        ctx: Context = None,
    ) -> str:
        """Fetch a single item (Task / Habit / Chore / Event) by any reference.

        ``item`` accepts any Ref input form and is resolved transparently:

        - a **UUID** (``GET /items/{id}``);
        - a **Sequence shorthand** -- ``#123`` or bare ``123``. This resolves
          against your **personal org only**, by design. For an item in a
          shared org, name it by its **Canonical ref** (``acme-123``) or its
          **App URL** instead -- both resolve across orgs;
        - a **Canonical ref** (``slug-123``, e.g. ``u-1y0e2v-123``);
        - an **App URL** (``https://app.defernowork.com/o/{org_slug}/items/{seq-or-id}``);
        - the unambiguous **GitHub Alias** ``owner/repo#N`` (it carries a ``/``,
          so it can't be confused with a Canonical ref) -- auto-routed to the
          by-alias endpoint.

        **Deferno-`#` vs GitHub-`#` ambiguity.** A *bare* ``#N`` always means a
        Deferno Sequence shorthand here; it is NOT inferred as a GitHub issue.
        Likewise an ambiguous string like ``ABC-223`` collides with a Canonical
        ref and is therefore NOT auto-routed to alias resolution. Inferring
        which a user means from conversation is the job of a future
        **context-adaptive** classifier (see CONTEXT.md "Flagged ambiguities"),
        not this tool. Until then, use ``as_alias=true`` to force the alias path.

        Args:
            item: Any Ref input form (or, with ``as_alias=true``, a raw alias).
            full: When ``true``, return the complete record (action history,
                comments, children, mood, attachments, ...) instead of the
                default compact projection.
            as_alias: When ``true``, BYPASS the Ref classifier and look ``item``
                up directly via ``GET /items/by-alias/{item}``. This is the
                explicit escape-hatch for ambiguous external aliases (e.g.
                ``ABC-223``) that the classifier deliberately will not
                auto-route. The unambiguous GitHub form ``owner/repo#N`` already
                routes to by-alias WITHOUT this flag.

        Returns a **compact** projection by default (a small whitelist of
        fields, including ``description``). Pass ``full=true`` for the complete
        record (action history, comments, children, mood, attachments, ...).
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                if as_alias:
                    # Explicit escape-hatch: skip classify_ref entirely and hit
                    # by-alias with the raw string (one call, returns the item).
                    record = await client.get_item_by_alias(item)
                else:
                    item_id = await resolve_ref(client, item)
                    record = await client.get_item(item_id)
            except DefernoError as exc:
                return format_error(exc)
        if full:
            return json.dumps(record)
        return json.dumps(project(record, COMPACT_ITEM_FIELDS))

    @mcp.tool()
    async def list_items(
        kind: str | None = None,
        status: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int | None = None,
        full: bool = False,
        window: str | None = None,
        ctx: Context = None,
    ) -> str:
        """List items of any kind (Task / Habit / Chore / Event), windowed.

        The canonical, bounded list view. Returns a **Compact** projection by
        default -- a small fixed field set per row (``ref``, ``kind``, ``title``,
        ``status``, ``complete_by``, ``parent_id``, ``labels``) with the heavy
        body (``description``) and raw ``id`` dropped -- so a query returns a
        trimmed set, not the entire working set in full detail.

        Filters (composed into an OData ``$filter`` with ``and``):

        - ``kind`` -- one of ``"task"``, ``"habit"``, ``"chore"``, ``"event"``.
        - ``status`` -- the item status (e.g. ``"open"``, ``"done"``).
        - ``from_date`` / ``to_date`` -- ``YYYY-MM-DD``; filter on ``complete_by``
          widened to RFC3339 day boundaries (start-of-day for ``from_date``,
          end-of-day for ``to_date``).

        An unknown / unfilterable field returns a backend 400, surfaced clearly
        (not swallowed).

        - ``limit`` -- maps to OData ``$top``. The backend caps ``$top`` at 500
          by REJECTING larger values with a 400 (it does NOT clamp); the number
          is passed through verbatim.
        - ``full=true`` -- return every field on each row (drops the projection).
        - ``window="all"`` -- opt out of the default done-visibility window for
          full history (the default window applies only to the unfiltered call).

        Regardless of projection, the backend always injects ``ref``,
        ``org_slug``, ``type`` and ``sequence`` into every row.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                rows = await client.list_items(
                    kind=kind,
                    status=status,
                    from_date=from_date,
                    to_date=to_date,
                    limit=limit,
                    full=full,
                    window=window,
                )
            except DefernoError as exc:
                return format_error(exc)
        if full:
            return json.dumps(rows)
        return json.dumps([project(row, COMPACT_ITEM_CORE_FIELDS) for row in rows])

    @mcp.tool()
    async def search_items(
        query: str,
        status: str | None = None,
        label: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        parent_id: str | None = None,
        full: bool = False,
        ctx: Context = None,
    ) -> str:
        """Full-text search over items, returning a Compact projection.

        The compact, kind-neutral replacement for ``search_tasks``. Returns a
        **Compact** projection by default -- the same small fixed field set per
        row as ``list_items`` (``ref``, ``kind``, ``title``, ``status``,
        ``complete_by``, ``parent_id``, ``labels``) -- so the heavy body
        (``description``) and the raw ``id`` are dropped. Pass ``full=true`` for
        the rows verbatim.

        Scope: **full-text search currently covers Tasks only.** This tool is
        backed by the Tasks search path (``GET /tasks/search``) because the
        backend has no kind-neutral ``/items/search`` endpoint today; a
        kind-neutral full-text search is a known **backend follow-on** (to be
        filed in the Deferno backend repo, out of scope for the MCP). Non-Task
        kinds (Habits / Chores / Events) are therefore not reached by ``query``
        yet -- use ``list_items`` to enumerate those.

        Args:
            query: Search query (min 2 characters). Searches title and description.
            status: Filter by status (open, in-progress, in-review, done, dropped).
            label: Filter by label tag.
            from_date: Filter items due on or after this ISO 8601 date.
            to_date: Filter items due on or before this ISO 8601 date.
            parent_id: Scope search to children of this item (UUID).
            full: When ``true``, return every field on each row (no projection).
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                rows = await client.search_tasks(
                    query,
                    status=status,
                    label=label,
                    from_date=from_date,
                    to_date=to_date,
                    parent_id=parent_id,
                )
            except DefernoError as exc:
                return format_error(exc)
        if full:
            return json.dumps(rows)
        return json.dumps([project(row, COMPACT_ITEM_CORE_FIELDS) for row in rows])

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

        ``item_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the conversion.

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
                item_id = await resolve_ref(client, item_id)
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
        """Return the change-history list for any item kind (Task/Habit/Chore/Event).

        ``item_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the history lookup.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                item_id = await resolve_ref(client, item_id)
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

        ``item_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the pin toggle.

        Backend body is ``{pinned: bool}`` -- the gap-closure plan's optional
        ``label`` argument is not part of this endpoint (custom pin labels
        live on ``PATCH /tasks/pinned/{id}``). Returns ``{"ok": true}`` on
        success (backend response is 204 NO_CONTENT).
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                item_id = await resolve_ref(client, item_id)
                await client.set_item_pinned(item_id, pinned)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"ok": True})
