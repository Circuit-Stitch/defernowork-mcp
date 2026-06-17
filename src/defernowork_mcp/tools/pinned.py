"""MCP tools for the sidebar Pinned-Tasks list (PR-D v0.2 surface).

Three operations on the user's pinned-tasks list:
  - ``list_pinned_tasks``   → ``GET /tasks/pinned``
  - ``reorder_pinned_tasks``→ ``POST /tasks/pinned/reorder``
  - ``update_pinned_label`` → ``PATCH /tasks/pinned/{id}``

These complement ``set_item_pinned`` (in tools/items.py), which is the
polymorphic on/off toggle for any item kind. ``set_item_pinned`` maintains
the underlying ``user:{uid}:pinned`` index; the tools in this module
operate on that already-pinned list (ordering + per-entry labels).
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
    async def list_pinned_tasks(ctx: Context = None) -> str:
        """List the user's sidebar-pinned items in display order.

        Returns a JSON array of ``{task: TaskSummary, label: str | null}``
        objects. The backend reconciles inconsistencies on every call —
        list entries whose underlying task is unpinned or deleted are
        dropped — so the result is always self-consistent and safe to
        render directly in the sidebar.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                pinned = await client.list_pinned_tasks()
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(pinned)

    @mcp.tool()
    async def reorder_pinned_tasks(
        task_ids: list[str],
        ctx: Context = None,
    ) -> str:
        """Replace the pinned-list ordering with ``task_ids``.

        Each element of ``task_ids`` accepts any reference form — UUID, sequence
        shorthand (``#123``, personal-org only), canonical ref (``acme-123``),
        or app URL — and is resolved to a UUID before the call (order
        preserved). The resolved set must be an exact permutation of the user's
        current pinned set: extra ids, missing ids, or duplicates all 400. To
        add or remove an item, use ``set_item_pinned`` first, then reorder.
        Returns ``{"reordered": True, "count": N}`` on success.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                task_ids = [await resolve_ref(client, t) for t in task_ids]
                await client.reorder_pinned_tasks(task_ids)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"reordered": True, "count": len(task_ids)})

    @mcp.tool()
    async def update_pinned_label(
        pinned_id: str,
        label: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Set or clear the custom sidebar label for a pinned task.

        ``pinned_id`` is the underlying task UUID (the pinned list keys
        on task id; there is no separate pin-record id, hence the route
        ``/tasks/pinned/{id}``). Pass ``label=None`` (or omit) to clear
        the label — this is the only way to clear it, so the body is
        always sent as ``{"label": label}`` including the JSON ``null``.
        404 if the task is not in the pinned list.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                await client.update_pinned_label(pinned_id, label)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"updated": True, "pinned_id": pinned_id})
