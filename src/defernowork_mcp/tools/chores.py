"""Chore-specific occurrence tool. Chore CRUD is the kind-neutral
``update_item`` / ``delete_item`` (tools/items.py); occurrence status/reschedule
are the kind-neutral occurrence tools (tools/occurrences.py). What stays here is
``mark_next_chore_done`` — it targets the *earliest unresolved* occurrence, not
a ref+date, so it has no kind-neutral equivalent."""

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
    async def mark_next_chore_done(
        chore_id: str,
        status: str = "done",
        ctx: Context = None,
    ) -> str:
        """Apply ``status`` to the earliest unresolved occurrence of a chore.

        ``chore_id`` accepts any item ref.

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
