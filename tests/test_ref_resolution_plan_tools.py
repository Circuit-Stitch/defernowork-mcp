"""Transparent ref resolution for the plan tools (issue #14).

The MCP modernization (#3-#11) made ``list_items`` return rows keyed by
``ref`` and made most id-taking mutations ref-aware (#7), but the plan tools
were left UUID-only — so the natural loop *"list_items -> add the top one to
today's plan"* broke: ``add_to_plan`` rejected the ``ref`` it was just handed.

This pins the fix: each of the 6 plan tools resolves any Ref input form to a
UUID before the backend call, mirroring #7. The ``reorder_*`` tools take a
**list** of ids -> each element is resolved independently.

Exercised through the public interface: a real FastMCP server (client pointed
at a respx-mocked backend), the tool looked up from the registry and invoked.
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
OTHER_UUID = "99999999-8888-7777-6666-555555555555"


def _env(data):
    return {"version": "0.2", "data": data, "error": None}


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


# ── add_to_plan: representative tool — succeeds given EACH ref form ────────────


@respx.mock
async def test_add_to_plan_uuid_form_no_resolve_http(server):
    """A UUID short-circuits resolve_ref (no resolve HTTP) and POSTs directly."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123")
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123")
    add = respx.post(f"{BASE}/tasks/plan/add").mock(
        return_value=httpx.Response(200, json=_env({"ok": True}))
    )

    result = await _call(server, "add_to_plan", task_id=TASK_UUID)
    out = json.loads(result)

    assert add.called
    # UUID short-circuits: no resolve round-trip whatsoever.
    assert not by_seq.called
    assert not by_ref.called
    body = json.loads(add.calls.last.request.content)
    assert body["task_id"] == TASK_UUID
    assert out["task_id"] == TASK_UUID


@respx.mock
async def test_add_to_plan_sequence_form(server):
    """``#123`` resolves via GET /items/by-seq/123, then POSTs the resolved uuid."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "task"}))
    )
    add = respx.post(f"{BASE}/tasks/plan/add").mock(
        return_value=httpx.Response(200, json=_env({"ok": True}))
    )

    result = await _call(server, "add_to_plan", task_id="#123")
    out = json.loads(result)

    assert by_seq.called and add.called
    body = json.loads(add.calls.last.request.content)
    assert body["task_id"] == TASK_UUID
    assert out["task_id"] == TASK_UUID


@respx.mock
async def test_add_to_plan_canonical_form(server):
    """``u-1y0e2v-123`` resolves via GET /items/by-ref/<canonical>, then POSTs."""
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "chore"}))
    )
    add = respx.post(f"{BASE}/tasks/plan/add").mock(
        return_value=httpx.Response(200, json=_env({"ok": True}))
    )

    result = await _call(server, "add_to_plan", task_id="u-1y0e2v-123")
    out = json.loads(result)

    assert by_ref.called and add.called
    body = json.loads(add.calls.last.request.content)
    assert body["task_id"] == TASK_UUID
    assert out["task_id"] == TASK_UUID


@respx.mock
async def test_add_to_plan_app_url_form(server):
    """An app URL with a sequence resolves by-REF (not by-seq), then POSTs."""
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "task"}))
    )
    add = respx.post(f"{BASE}/tasks/plan/add").mock(
        return_value=httpx.Response(200, json=_env({"ok": True}))
    )

    result = await _call(
        server,
        "add_to_plan",
        task_id="https://app.defernowork.com/o/u-1y0e2v/items/123",
    )
    out = json.loads(result)

    assert by_ref.called and add.called
    body = json.loads(add.calls.last.request.content)
    assert body["task_id"] == TASK_UUID
    assert out["task_id"] == TASK_UUID


@respx.mock
async def test_add_to_plan_not_auto_routed_surfaces_400_and_skips_post(server):
    """``ABC-223`` (uppercase alias) is not auto-routed -> DefernoError 400 locally.

    The plan POST must NOT fire, and the returned string is a clear error.
    """
    add = respx.post(f"{BASE}/tasks/plan/add")

    result = await _call(server, "add_to_plan", task_id="ABC-223")

    assert isinstance(result, str)
    assert "400" in result
    assert "not an auto-routable" in result
    assert not add.called


# ── remove_from_plan / items-plan add+remove: one ref form each ───────────────


@respx.mock
async def test_remove_from_plan_sequence_form(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "task"}))
    )
    remove = respx.post(f"{BASE}/tasks/plan/remove").mock(
        return_value=httpx.Response(200, json=_env({"ok": True}))
    )

    result = await _call(server, "remove_from_plan", task_id="#123")
    out = json.loads(result)

    assert by_seq.called and remove.called
    body = json.loads(remove.calls.last.request.content)
    assert body["task_id"] == TASK_UUID
    assert out["task_id"] == TASK_UUID


@respx.mock
async def test_add_to_items_plan_canonical_form(server):
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "habit"}))
    )
    add = respx.post(f"{BASE}/items/plan/add").mock(
        return_value=httpx.Response(200, json=_env({"ok": True}))
    )

    await _call(server, "add_to_items_plan", task_id="u-1y0e2v-123")

    assert by_ref.called and add.called
    body = json.loads(add.calls.last.request.content)
    assert body["task_id"] == TASK_UUID


@respx.mock
async def test_remove_from_items_plan_sequence_form(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "event"}))
    )
    remove = respx.post(f"{BASE}/items/plan/remove").mock(
        return_value=httpx.Response(200, json=_env({"ok": True}))
    )

    await _call(server, "remove_from_items_plan", task_id="#123")

    assert by_seq.called and remove.called
    body = json.loads(remove.calls.last.request.content)
    assert body["task_id"] == TASK_UUID


# ── reorder_* : resolve EACH element of the id list ───────────────────────────


@respx.mock
async def test_reorder_plan_resolves_each_id_in_list(server):
    """reorder_plan resolves every element; a UUID short-circuits, a ref resolves."""
    by_seq = respx.get(f"{BASE}/items/by-seq/456").mock(
        return_value=httpx.Response(200, json=_env({"id": OTHER_UUID, "kind": "task"}))
    )
    reorder = respx.post(f"{BASE}/tasks/plan/reorder").mock(
        return_value=httpx.Response(200, json=_env({"ok": True}))
    )

    result = await _call(server, "reorder_plan", task_ids=[TASK_UUID, "#456"])
    out = json.loads(result)

    assert by_seq.called and reorder.called
    body = json.loads(reorder.calls.last.request.content)
    # Each element resolved to a UUID, order preserved.
    assert body["task_ids"] == [TASK_UUID, OTHER_UUID]
    assert out["count"] == 2


@respx.mock
async def test_reorder_items_plan_resolves_each_id_in_list(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/456").mock(
        return_value=httpx.Response(200, json=_env({"id": OTHER_UUID, "kind": "chore"}))
    )
    reorder = respx.post(f"{BASE}/items/plan/reorder").mock(
        return_value=httpx.Response(200, json=_env({"ok": True}))
    )

    await _call(server, "reorder_items_plan", task_ids=[TASK_UUID, "#456"])

    assert by_seq.called and reorder.called
    body = json.loads(reorder.calls.last.request.content)
    assert body["task_ids"] == [TASK_UUID, OTHER_UUID]
