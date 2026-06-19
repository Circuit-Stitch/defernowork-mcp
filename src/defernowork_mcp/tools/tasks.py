"""Task CRUD + tree operation tools."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from mcp.server.fastmcp import Context, FastMCP

from ..client import DefernoClient, DefernoError
from ..refs import resolve_ref

_UNSET = object()


def register(
    mcp: FastMCP,
    get_client: Callable[..., Awaitable[DefernoClient]],
    format_error: Callable[[DefernoError], str],
    compact: Callable[[dict[str, Any]], dict[str, Any]],
    unset: object,
) -> None:
    @mcp.tool()
    async def create_task(
        title: str,
        description: str,
        labels: list[str] | None = unset,
        parent_id: str | None = unset,
        assignee: str | None = unset,
        complete_by: str | None = unset,
        productive: float | None = unset,
        desire: float | None = unset,
        recurrence: dict[str, Any] | None = unset,
        recurring_type: str | None = unset,
        ctx: Context = None,
    ) -> str:
        """Create a new task.

        ``complete_by`` must be an ISO-8601 UTC timestamp.
        ``parent_id`` attaches the new task as a child of an existing item and
        accepts any item ref. Omit it (or pass ``null``) to create at root.
        ``productive`` and ``desire`` are floats in [0, 1] representing how
        productive this task feels and how much the user wants to do it.
        ``recurrence`` sets a repeat schedule. Use ``{"type": "daily"}``,
        ``{"type": "every_n_days", "n": 3}``, or
        ``{"type": "weekly", "days": ["Mon", "Wed", "Fri"]}``.
        ``recurring_type`` controls behavior when a recurring task is missed.
        Must be one of ``"chore"`` (lingers until done, default),
        ``"habit"`` (fresh start each day), or ``"event"`` (time-bound,
        can't be made up). Only meaningful when ``recurrence`` is set.

        v0.2 optional field:
        - ``occurrence_id``: when this Task is a materialized subtask of a
          recurring entity's occurrence, the Occurrence id it belongs to.
          Normal tasks omit this field.
        """
        payload = compact(
            {
                "title": title,
                "description": description,
                "labels": labels,
                "parent_id": parent_id,
                "assignee": assignee,
                "complete_by": complete_by,
                "productive": productive,
                "desire": desire,
                "recurrence": recurrence,
                "recurring_type": recurring_type,
            }
        )
        async with (await get_client(ctx=ctx)) as client:
            try:
                if parent_id is not unset and parent_id is not None:
                    payload["parent_id"] = await resolve_ref(client, parent_id)
                task = await client.create_task(payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(task)

    @mcp.tool()
    async def split_task(
        task_id: str,
        first_title: str,
        first_description: str,
        second_title: str,
        second_description: str,
        ctx: Context = None,
    ) -> str:
        """Decompose a task into two child tasks while preserving the parent.

        ``task_id`` accepts any item ref.

        Returns the updated parent and both new children.
        """
        payload = {
            "first_title": first_title,
            "first_description": first_description,
            "second_title": second_title,
            "second_description": second_description,
        }
        async with (await get_client(ctx=ctx)) as client:
            try:
                task_id = await resolve_ref(client, task_id)
                result = await client.split_task(task_id, payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)

    @mcp.tool()
    async def fold_task(
        task_id: str,
        title: str,
        description: str,
        labels: list[str] | None = None,
        desire: float | None = None,
        productive: float | None = None,
        complete_by: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Insert a new next-step task directly after ``task_id`` in the sequence.

        ``task_id`` accepts any item ref.

        Preserves any existing downstream chain. Returns the original task
        and the newly created next task.
        """
        payload = compact(
            {
                "title": title,
                "description": description,
                "labels": labels,
                "desire": desire,
                "productive": productive,
                "complete_by": complete_by,
            }
        )
        async with (await get_client(ctx=ctx)) as client:
            try:
                task_id = await resolve_ref(client, task_id)
                result = await client.fold_task(task_id, payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)

    @mcp.tool()
    async def merge_task(task_id: str, ctx: Context = None) -> str:
        """Roll the active children of a task back into the parent.

        ``task_id`` accepts any item ref.

        Child content is appended to the parent description; the children are
        marked as ``pruned`` but remain recoverable. Pass the id of any
        child whose parent should receive the merge.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                task_id = await resolve_ref(client, task_id)
                result = await client.merge_task(task_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)

    @mcp.tool()
    async def get_mood_history(ctx: Context = None) -> str:
        """Return the user's historical mood-per-task log for finished tasks."""
        async with (await get_client(ctx=ctx)) as client:
            try:
                history = await client.mood_history()
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(history)

    @mcp.tool()
    async def export_data(ctx: Context = None) -> str:
        """Export all user data as JSON.

        Returns a complete backup of all tasks (with full history, mood
        vectors, recurrence rules), root ordering, and daily plans.
        The export can be imported via the Deferno web UI settings page.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                result = await client.export_data()
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)

    @mcp.tool()
    async def import_data(
        data: dict[str, Any] | None = None,
        ctx: Context = None,
    ) -> str:
        """Import an ExportData blob produced by ``export_data``.

        ``data`` should be the full ExportData object (with keys ``tasks``,
        ``events``, ``habits``, ``chores``, ``root_order``, ``daily_plans``).
        Pass an empty dict to dry-run.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                result = await client.import_data(data or {})
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)

    @mcp.tool()
    async def promote_task(
        task_id: str,
        target_org_id: str,
        ctx: Context = None,
    ) -> str:
        """Promote a personal-org task into a target org.

        Moves the task from the caller's personal org into ``target_org_id``,
        re-encrypting it under the target org's data-encryption key. The
        caller must own the task in their personal org AND be a member of
        ``target_org_id``. Returns JSON ``null`` on success (the backend
        returns no body).
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                await client.promote_task(task_id, target_org_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(None)

    @mcp.tool()
    async def batch_tasks(
        operations: list[dict[str, Any]],
        ctx: Context = None,
    ) -> str:
        """Execute multiple task operations atomically in a single call.

        ``operations`` is a list of operation objects. Each must have an
        ``op`` field (``"update"`` or ``"move"``) and a ``task_id``.

        Update operations accept the Task mutable fields (``title``,
        ``description``, ``status``, ``labels``, etc.) at the top level alongside
        ``op`` and ``task_id``. (This is Tasks-only batch; for a single item of
        any kind use ``update_item``.)

        Move operations accept ``new_parent_id`` (null for root) and an
        optional ``position`` (insertion index).

        Both ``task_id`` and ``new_parent_id`` in each operation are any item
        ref; a ``new_parent_id`` of ``null`` (detach to root) is left as-is.

        All operations succeed or none do (all-or-nothing).  On success
        returns ``{"tasks": [...]}``, the list of all modified tasks.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                for op in operations:
                    if op.get("task_id") is not None:
                        op["task_id"] = await resolve_ref(client, op["task_id"])
                    if op.get("new_parent_id") is not None:
                        op["new_parent_id"] = await resolve_ref(
                            client, op["new_parent_id"]
                        )
                result = await client.batch(operations)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)
