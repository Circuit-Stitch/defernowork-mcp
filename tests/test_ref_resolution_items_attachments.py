"""Transparent ref resolution wiring for items.py + task_attachments.py (issue #7 part B).

Part A's tests/test_ref_resolution_tasks.py carries the heavy per-form matrix. This
file is the light per-file proof that the Part B tools are wired the same way:

- ``convert_item`` / ``get_item_history`` / ``set_item_pinned`` (items.py) resolve
  ``item_id`` before acting; a UUID short-circuits with no resolve HTTP.
- ``list_task_attachments`` / ``delete_task_attachment`` (task_attachments.py) resolve
  ``task_id``; ``delete_task_attachment`` leaves ``att_id`` unresolved (passed through
  verbatim).
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
ATT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


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


# ── items.py: convert_item resolves item_id, then POSTs the resolved uuid ─────


@respx.mock
async def test_convert_item_sequence_form_resolves_then_converts(server):
    """``#123`` resolves via GET /items/by-seq/123, then POSTs /items/{uuid}/convert."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "task"}))
    )
    convert = respx.post(f"{BASE}/items/{ITEM_UUID}/convert").mock(
        return_value=httpx.Response(201, json=_env({"id": ITEM_UUID, "kind": "chore"}))
    )

    result = await _call(server, "convert_item", item_id="#123", to="chore")
    out = json.loads(result)

    assert by_seq.called and convert.called
    assert convert.calls.last.request.url.path == f"/api/items/{ITEM_UUID}/convert"
    assert out["id"] == ITEM_UUID


@respx.mock
async def test_convert_item_uuid_form_no_resolve_http(server):
    """A UUID short-circuits resolve_ref (no resolve HTTP) and POSTs directly."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123")
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123")
    convert = respx.post(f"{BASE}/items/{ITEM_UUID}/convert").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "task"}))
    )

    result = await _call(server, "convert_item", item_id=ITEM_UUID, to="task")
    out = json.loads(result)

    assert convert.called
    # UUID short-circuits: no resolve round-trip whatsoever.
    assert not by_seq.called
    assert not by_ref.called
    assert out["id"] == ITEM_UUID


@respx.mock
async def test_get_item_history_canonical_form_resolves_then_gets(server):
    """``acme-123`` resolves via by-ref, then GETs /items/{uuid}/history."""
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "task"}))
    )
    history = respx.get(f"{BASE}/items/{ITEM_UUID}/history").mock(
        return_value=httpx.Response(200, json=_env([{"action": "created"}]))
    )

    result = await _call(server, "get_item_history", item_id="u-1y0e2v-123")
    out = json.loads(result)

    assert by_ref.called and history.called
    assert history.calls.last.request.url.path == f"/api/items/{ITEM_UUID}/history"
    assert out == [{"action": "created"}]


@respx.mock
async def test_set_item_pinned_sequence_form_resolves_then_pins(server):
    """``#123`` resolves via by-seq, then POSTs /items/{uuid}/pin."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "task"}))
    )
    pin = respx.post(f"{BASE}/items/{ITEM_UUID}/pin").mock(
        return_value=httpx.Response(204)
    )

    result = await _call(server, "set_item_pinned", item_id="#123", pinned=True)
    out = json.loads(result)

    assert by_seq.called and pin.called
    assert pin.calls.last.request.url.path == f"/api/items/{ITEM_UUID}/pin"
    assert out == {"ok": True}


# ── task_attachments.py: resolve task_id; att_id stays unresolved ─────────────


@respx.mock
async def test_list_task_attachments_sequence_form_resolves_then_lists(server):
    """``#123`` resolves via by-seq, then GETs /tasks/{uuid}/attachments."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "task"}))
    )
    listing = respx.get(f"{BASE}/tasks/{ITEM_UUID}/attachments").mock(
        return_value=httpx.Response(200, json=_env([{"id": ATT_ID, "provider": "s3"}]))
    )

    result = await _call(server, "list_task_attachments", task_id="#123")
    out = json.loads(result)

    assert by_seq.called and listing.called
    assert listing.calls.last.request.url.path == f"/api/tasks/{ITEM_UUID}/attachments"
    assert out == [{"id": ATT_ID, "provider": "s3"}]


@respx.mock
async def test_delete_task_attachment_resolves_task_id_passes_att_id_verbatim(server):
    """task_id resolves; att_id is passed through UNRESOLVED into the DELETE path.

    ``att_id`` is an attachment id, not an item Ref input form. The single DELETE
    path assertion proves both the task_id resolve and the att_id passthrough.
    """
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "task"}))
    )
    delete = respx.delete(
        f"{BASE}/tasks/{ITEM_UUID}/attachments/{ATT_ID}"
    ).mock(return_value=httpx.Response(204))

    result = await _call(
        server, "delete_task_attachment", task_id="#123", att_id=ATT_ID
    )
    out = json.loads(result)

    assert by_seq.called and delete.called
    # DELETE path = resolved task uuid + att_id verbatim (never resolved).
    assert (
        delete.calls.last.request.url.path
        == f"/api/tasks/{ITEM_UUID}/attachments/{ATT_ID}"
    )
    assert out == {"ok": True}


# ── resolution failure: clear error, NO operation issued ──────────────────────


@respx.mock
async def test_convert_item_not_auto_routed_surfaces_400_and_skips_convert(server):
    """``ABC-223`` (uppercase alias) is not auto-routed -> DefernoError 400 locally.

    The convert POST must NOT fire, and the returned string is a clear error.
    """
    convert = respx.post(f"{BASE}/items/{ITEM_UUID}/convert").mock(
        return_value=httpx.Response(201, json=_env({"id": ITEM_UUID, "kind": "chore"}))
    )

    result = await _call(server, "convert_item", item_id="ABC-223", to="chore")

    assert isinstance(result, str)
    assert "400" in result
    assert "not an auto-routable" in result
    # The operation must NOT have run against an unresolved ref.
    assert not convert.called


@respx.mock
async def test_delete_task_attachment_not_auto_routed_surfaces_400_and_skips_delete(
    server,
):
    """A NOT_AUTO_ROUTED task_id surfaces a clear error and issues no DELETE."""
    delete = respx.delete(
        f"{BASE}/tasks/{ITEM_UUID}/attachments/{ATT_ID}"
    ).mock(return_value=httpx.Response(204))

    result = await _call(
        server, "delete_task_attachment", task_id="ABC-223", att_id=ATT_ID
    )

    assert isinstance(result, str)
    assert "400" in result
    assert "not an auto-routable" in result
    assert not delete.called
