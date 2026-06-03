"""Transparent ref resolution wiring for chores.py + habits.py + events.py (issue #7 part C).

Part A's tests/test_ref_resolution_tasks.py carries the heavy per-form matrix. This
file is the light per-file proof that the Part C tools are wired the same way:

- chores.py: a non-UUID ``chore_id`` resolves before the occurrence op hits the
  resolved-uuid path; a UUID short-circuits with no resolve HTTP.
- habits.py: a non-UUID ``habit_id`` resolves before the op hits the resolved-uuid path.
- events.py: ``update_event`` / ``delete_event`` resolve ``event_id`` before acting.
- A NOT_AUTO_ROUTED ref surfaces a clear error and issues NO operation.

Tools are exercised through the public interface: a real FastMCP server built by
``create_server`` (client pointed at a respx-mocked backend), the tool looked up from
the registry and invoked.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from defernowork_mcp import server as srv
from defernowork_mcp.client import DefernoClient

BASE = "http://test:3000/api"
ITEM_UUID = "11111111-2222-3333-4444-555555555555"


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


# ── chores.py: resolve chore_id, then hit the resolved-uuid occurrence path ───


@respx.mock
async def test_set_chore_occurrence_status_sequence_form_resolves_then_acts(server):
    """``#123`` resolves via GET /items/by-seq/123, then PUTs /chores/{uuid}/occurrences/{date}."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "chore"}))
    )
    set_status = respx.put(
        f"{BASE}/chores/{ITEM_UUID}/occurrences/2026-06-03"
    ).mock(
        return_value=httpx.Response(200, json=_env({"date": "2026-06-03", "status": "DoneOnTime"}))
    )

    result = await _call(
        server,
        "set_chore_occurrence_status",
        chore_id="#123",
        date="2026-06-03",
        status="done",
    )
    out = json.loads(result)

    assert by_seq.called and set_status.called
    assert (
        set_status.calls.last.request.url.path
        == f"/api/chores/{ITEM_UUID}/occurrences/2026-06-03"
    )
    assert out["status"] == "DoneOnTime"


@respx.mock
async def test_update_chore_uuid_form_no_resolve_http(server):
    """A UUID short-circuits resolve_ref (no resolve HTTP) and PATCHes directly."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123")
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123")
    patch = respx.patch(f"{BASE}/chores/{ITEM_UUID}").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "Chore", "title": "x"}))
    )

    result = await _call(server, "update_chore", chore_id=ITEM_UUID, title="x")
    out = json.loads(result)

    assert patch.called
    # UUID short-circuits: no resolve round-trip whatsoever.
    assert not by_seq.called
    assert not by_ref.called
    assert out["id"] == ITEM_UUID


# ── habits.py: resolve habit_id, then hit the resolved-uuid occurrence path ───


@respx.mock
async def test_mark_habit_occurrence_canonical_form_resolves_then_acts(server):
    """``acme-123`` resolves via by-ref, then POSTs /habits/{uuid}/occurrences."""
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "habit"}))
    )
    mark = respx.post(f"{BASE}/habits/{ITEM_UUID}/occurrences").mock(
        return_value=httpx.Response(200, json=_env({"date": "2026-06-03", "done": True}))
    )

    result = await _call(
        server, "mark_habit_occurrence", habit_id="u-1y0e2v-123", done=True, date="2026-06-03"
    )
    out = json.loads(result)

    assert by_ref.called and mark.called
    assert mark.calls.last.request.url.path == f"/api/habits/{ITEM_UUID}/occurrences"
    assert out["done"] is True


# ── events.py: resolve event_id, then hit the resolved-uuid entity path ───────


@respx.mock
async def test_delete_event_sequence_form_resolves_then_deletes(server):
    """``#123`` resolves via by-seq, then DELETEs /events/{uuid}."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    delete = respx.delete(f"{BASE}/events/{ITEM_UUID}").mock(
        return_value=httpx.Response(204)
    )

    result = await _call(server, "delete_event", event_id="#123")
    out = json.loads(result)

    assert by_seq.called and delete.called
    assert delete.calls.last.request.url.path == f"/api/events/{ITEM_UUID}"
    assert out == {"deleted": True, "event_id": ITEM_UUID}


@respx.mock
async def test_update_event_canonical_form_resolves_then_patches(server):
    """``acme-123`` resolves via by-ref, then PATCHes /events/{uuid}."""
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    patch = respx.patch(f"{BASE}/events/{ITEM_UUID}").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "Event", "title": "y"}))
    )

    result = await _call(server, "update_event", event_id="u-1y0e2v-123", title="y")
    out = json.loads(result)

    assert by_ref.called and patch.called
    assert patch.calls.last.request.url.path == f"/api/events/{ITEM_UUID}"
    assert out["id"] == ITEM_UUID


# ── resolution failure: clear error, NO operation issued ──────────────────────


@respx.mock
async def test_update_chore_not_auto_routed_surfaces_400_and_skips_patch(server):
    """``ABC-223`` (uppercase alias) is not auto-routed -> DefernoError 400 locally.

    The chore PATCH must NOT fire, and the returned string is a clear error.
    """
    patch = respx.patch(f"{BASE}/chores/{ITEM_UUID}").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "Chore", "title": "x"}))
    )

    result = await _call(server, "update_chore", chore_id="ABC-223", title="x")

    assert isinstance(result, str)
    assert "400" in result
    assert "not an auto-routable" in result
    # The operation must NOT have run against an unresolved ref.
    assert not patch.called
