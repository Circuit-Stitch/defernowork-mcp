"""Transparent ref resolution for the #14 *secondary* id args.

Issue #14's MUST is the 6 plan tools (see test_ref_resolution_plan_tools.py).
This file pins the "(decide during triage)" secondary set — the remaining
id-taking args that pair naturally with a ``list_items`` ``ref``:

- ``create_task`` — the ``parent_id`` arg (creation tools were excluded from
  #7). ``parent_id`` defaults to the unset sentinel, so it is resolved ONLY
  when a real ref is supplied (unset / None pass through untouched).
  (create_chore/habit/event were folded into capture_item, which carries no
  parent_id — ADR-0003 keeps parent_id a create_task-only escape.)
- ``search_items`` — the ``parent_id`` filter (forwarded as a query param).
- ``batch_tasks`` — nested operation ids (``task_id``, ``new_parent_id``); a
  ``new_parent_id`` of ``null`` (detach to root) is left as-is.
- ``reorder_pinned_tasks`` — every element of the ``task_ids`` list.

Genuinely UUID-only args (``update_pinned_label.pinned_id``,
``update_comment``/``delete_comment`` ``comment_id``) are out of scope and not
touched.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from defernowork_mcp import server as srv
from defernowork_mcp.client import DefernoClient

BASE = "http://test:3000/api"
TASK_UUID = "11111111-2222-3333-4444-555555555555"
PARENT_UUID = "99999999-8888-7777-6666-555555555555"
SECOND_UUID = "22222222-2222-2222-2222-222222222222"


def _env(data):
    return {"version": "0.2", "data": data, "error": None}


def _item(uuid=TASK_UUID, kind="task", **extra):
    body = {"kind": kind, "type": kind, "id": uuid, "title": "x", "status": "open"}
    body.update(extra)
    return body


@pytest.fixture
def server(monkeypatch):
    async def _stub_get_client_async(ctx=None):
        return DefernoClient(base_url=BASE, token="test-token")

    monkeypatch.setattr(srv, "_get_client_async", _stub_get_client_async)
    monkeypatch.setattr(srv, "_http_transport_mode", False)
    return srv.create_server()


def _tool(mcp, name):
    tools = getattr(mcp, "_tool_manager", None) or getattr(mcp, "tool_manager", None)
    for attr in ("_tools", "tools"):
        tool_map = getattr(tools, attr, None)
        if isinstance(tool_map, dict) and name in tool_map:
            return tool_map[name]
    raise LookupError(f"tool {name!r} not registered")


async def _call(mcp, name, **kwargs):
    tool = _tool(mcp, name)
    return await tool.fn(**kwargs)


# ── create_* parent_id: resolve only a supplied ref; unset passes through ─────


@respx.mock
async def test_create_task_parent_id_sequence_resolves(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/456").mock(
        return_value=httpx.Response(200, json=_env(_item(PARENT_UUID)))
    )
    create = respx.post(f"{BASE}/tasks").mock(
        return_value=httpx.Response(201, json=_env(_item()))
    )

    await _call(server, "create_task", title="t", description="d", parent_id="#456")

    assert by_seq.called and create.called
    body = json.loads(create.calls.last.request.content)
    assert body["parent_id"] == PARENT_UUID


@respx.mock
async def test_create_task_no_parent_id_no_resolve(server):
    """No parent_id supplied -> no resolve round-trip, no parent_id in the body."""
    by_seq = respx.get(f"{BASE}/items/by-seq/456")
    create = respx.post(f"{BASE}/tasks").mock(
        return_value=httpx.Response(201, json=_env(_item()))
    )

    await _call(server, "create_task", title="t", description="d")

    assert create.called
    assert not by_seq.called
    body = json.loads(create.calls.last.request.content)
    assert "parent_id" not in body


# ── search_items parent_id filter ─────────────────────────────────────────────


@respx.mock
async def test_search_items_parent_id_sequence_resolves(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/456").mock(
        return_value=httpx.Response(200, json=_env(_item(PARENT_UUID)))
    )
    search = respx.get(url__startswith=f"{BASE}/tasks/search").mock(
        return_value=httpx.Response(200, json=_env([]))
    )

    await _call(server, "search_items", query="foo", parent_id="#456")

    assert by_seq.called and search.called
    # The resolved UUID is forwarded as the parent_id query param.
    assert f"parent_id={PARENT_UUID}" in str(search.calls.last.request.url)


@respx.mock
async def test_search_items_no_parent_id_no_resolve(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/456")
    search = respx.get(url__startswith=f"{BASE}/tasks/search").mock(
        return_value=httpx.Response(200, json=_env([]))
    )

    await _call(server, "search_items", query="foo")

    assert search.called
    assert not by_seq.called
    assert "parent_id=" not in str(search.calls.last.request.url)


# ── batch_tasks: resolve nested task_id + new_parent_id; null parent stays null ─


@respx.mock
async def test_batch_tasks_resolves_nested_ids(server):
    by_seq_task = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env(_item(TASK_UUID)))
    )
    by_seq_parent = respx.get(f"{BASE}/items/by-seq/456").mock(
        return_value=httpx.Response(200, json=_env(_item(PARENT_UUID)))
    )
    batch = respx.post(f"{BASE}/tasks/batch").mock(
        return_value=httpx.Response(200, json=_env({"tasks": []}))
    )

    await _call(
        server,
        "batch_tasks",
        operations=[
            {"op": "update", "task_id": "#123", "status": "done"},
            {"op": "move", "task_id": SECOND_UUID, "new_parent_id": "#456"},
        ],
    )

    assert by_seq_task.called and by_seq_parent.called and batch.called
    ops = json.loads(batch.calls.last.request.content)["operations"]
    assert ops[0]["task_id"] == TASK_UUID  # ref -> resolved
    assert ops[1]["task_id"] == SECOND_UUID  # already a UUID, unchanged
    assert ops[1]["new_parent_id"] == PARENT_UUID  # ref -> resolved


@respx.mock
async def test_batch_tasks_move_null_parent_stays_null(server):
    by_seq_task = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env(_item(TASK_UUID)))
    )
    batch = respx.post(f"{BASE}/tasks/batch").mock(
        return_value=httpx.Response(200, json=_env({"tasks": []}))
    )

    await _call(
        server,
        "batch_tasks",
        operations=[{"op": "move", "task_id": "#123", "new_parent_id": None}],
    )

    assert by_seq_task.called and batch.called
    ops = json.loads(batch.calls.last.request.content)["operations"]
    assert ops[0]["task_id"] == TASK_UUID
    assert ops[0]["new_parent_id"] is None  # detach-to-root, never resolved


# ── reorder_pinned_tasks: resolve each element of the list ────────────────────


@respx.mock
async def test_reorder_pinned_tasks_resolves_each_id(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/456").mock(
        return_value=httpx.Response(200, json=_env(_item(PARENT_UUID)))
    )
    reorder = respx.post(f"{BASE}/tasks/pinned/reorder").mock(
        return_value=httpx.Response(204)
    )

    result = await _call(server, "reorder_pinned_tasks", task_ids=[TASK_UUID, "#456"])
    out = json.loads(result)

    assert by_seq.called and reorder.called
    body = json.loads(reorder.calls.last.request.content)
    assert body["task_ids"] == [TASK_UUID, PARENT_UUID]
    assert out["count"] == 2
