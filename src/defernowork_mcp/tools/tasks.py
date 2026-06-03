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
        ``parent_id`` attaches the new task as a child of an existing task.
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
                task = await client.create_task(payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(task)

    @mcp.tool()
    async def update_task(
        task_id: str,
        title: str | None = unset,
        description: str | None = unset,
        status: str | None = unset,
        labels: list[str] | None = unset,
        assignee: str | None = unset,
        complete_by: str | None = unset,
        productive: float | None = unset,
        desire: float | None = unset,
        recurrence: dict[str, Any] | None = unset,
        recurring_scope: str | None = unset,
        recurrence_id: str | None = unset,
        recurring_type: str | None = unset,
        ctx: Context = None,
    ) -> str:
        """Patch mutable fields on a task.

        ``task_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL
        — and is resolved to a UUID before the update.

        ``status`` must be one of ``open``, ``in-progress``, ``in-review``,
        ``done``, ``dropped``, ``pruned``. The backend rejects completing a
        task while any of its children are still active.

        Pass ``None`` explicitly to clear a field (e.g. ``complete_by=None``
        removes the deadline). Omitting a parameter leaves it unchanged.

        ``recurrence`` sets or clears a repeat schedule (see ``create_task``).

        ``recurring_type`` can be ``"chore"``, ``"habit"``, or ``"event"``
        (see ``create_task`` for details). Pass ``None`` to clear.

        For recurring tasks, if you change title, description, labels, or
        complete_by, you MUST also provide ``recurring_scope``:
        ``"this"`` (single instance), ``"following"`` (this and future),
        or ``"all"`` (entire series). ``"this"`` and ``"following"`` also
        require ``recurrence_id`` (the ISO start time of the instance).
        If the task is recurring and scope is missing, the call will fail
        with a message asking you to specify the scope — ask the user
        which option they prefer.

        v0.2 optional field:
        - ``occurrence_id``: when this Task is a materialized subtask of a
          recurring entity's occurrence, the Occurrence id it belongs to.
          Normal tasks omit this field.
        """
        payload = compact(
            {
                "title": title,
                "description": description,
                "status": status,
                "labels": labels,
                "assignee": assignee,
                "complete_by": complete_by,
                "productive": productive,
                "desire": desire,
                "recurrence": recurrence,
                "recurring_scope": recurring_scope,
                "recurrence_id": recurrence_id,
                "recurring_type": recurring_type,
            }
        )
        async with (await get_client(ctx=ctx)) as client:
            try:
                # Resolve any Ref input form to a UUID FIRST: the recurring-scope
                # get_task check below and the update_task call are both UUID-only.
                task_id = await resolve_ref(client, task_id)
                # Check if this is a recurring task needing a scope.
                if recurring_scope is unset:
                    deferno_fields = {"title", "description", "labels", "complete_by"}
                    has_deferno_changes = any(k in payload for k in deferno_fields)
                    if has_deferno_changes:
                        task_data = await client.get_task(task_id)
                        if task_data.get("series_id"):
                            return (
                                "This is a recurring task. Please specify "
                                "recurring_scope: 'this' (single instance), "
                                "'following' (this and future events), or "
                                "'all' (entire series). "
                                "Ask the user which option they prefer."
                            )

                task = await client.update_task(task_id, payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(task)

    @mcp.tool()
    async def set_task_status(task_id: str, status: str, ctx: Context = None) -> str:
        """Convenience wrapper around ``update_task`` for status changes.

        ``task_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL.

        Accepts ``open``, ``in-progress``, ``in-review``, ``done``, ``dropped``, ``pruned``.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                task_id = await resolve_ref(client, task_id)
                task = await client.update_task(task_id, {"status": status})
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(task)

    @mcp.tool()
    async def move_task(
        task_id: str,
        new_parent_id: str | None = None,
        position: int | None = None,
        ctx: Context = None,
    ) -> str:
        """Move a task to a different parent or reorder within its current parent.

        ``task_id`` and ``new_parent_id`` each accept any reference form — UUID,
        sequence shorthand (``#123``, personal-org only), canonical ref
        (``acme-123``), or app URL — and are resolved to UUIDs before the move.

        ``new_parent_id=None`` detaches the task to root level (kept as-is, not
        resolved). ``position`` is the insertion index in the target's children
        list (0 = first). Omit to append at end.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                task_id = await resolve_ref(client, task_id)
                if new_parent_id is not None:
                    new_parent_id = await resolve_ref(client, new_parent_id)
                task = await client.move_task(task_id, new_parent_id, position)
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

        ``task_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL.

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

        ``task_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL.

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

        ``task_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL.

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
    async def delete_task(task_id: str, ctx: Context = None) -> str:
        """Hard-delete a task by id.

        ``task_id`` accepts any reference form — UUID, sequence shorthand
        (``#123``, personal-org only), canonical ref (``acme-123``), or app URL.
        The returned ``task_id`` is the resolved UUID the deletion ran against.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                task_id = await resolve_ref(client, task_id)
                await client.delete_task(task_id)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps({"deleted": True, "task_id": task_id})

    @mcp.tool()
    async def get_tasks_calendar(
        start: str,
        end: str,
        tz: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Calendar view of tasks (recurring expansions + due dates).

        ``start`` and ``end`` are YYYY-MM-DD strings; ``end`` is exclusive.
        ``tz`` is an optional IANA timezone for local-midnight alignment.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                events = await client.get_calendar_events(start, end, tz=tz)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(events)

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

        Update operations accept the same fields as ``update_task``
        (``title``, ``description``, ``status``, ``labels``, etc.) at the
        top level alongside ``op`` and ``task_id``.

        Move operations accept ``new_parent_id`` (UUID or null for root)
        and an optional ``position`` (insertion index).

        All operations succeed or none do (all-or-nothing).  On success
        returns ``{"tasks": [...]}``, the list of all modified tasks.
        """
        async with (await get_client(ctx=ctx)) as client:
            try:
                result = await client.batch(operations)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)
