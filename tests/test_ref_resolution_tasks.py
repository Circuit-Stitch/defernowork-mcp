"""Transparent ref resolution for the ``tasks.py`` mutation tools (issue #7 part A).

Exercises the tools through the public interface: a real FastMCP server built by
``create_server`` (client pointed at a respx-mocked backend), the tool looked up
from the registry and invoked.

This is the representative-coverage burden for issue #7 as a whole: a
representative mutation (``set_task_status``) succeeds given EACH Ref input form,
and a resolution failure surfaces a clear error WITHOUT issuing the mutation.
Plus the ``move_item`` (both ids + None passthrough) and ``update_task``
(recurring-scope ``get_task`` uses the resolved UUID) specifics.
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


def _env(data):
    return {"version": "0.2", "data": data, "error": None}


def _task(status="open", **extra):
    body = {
        "kind": "task",
        "type": "task",
        "id": TASK_UUID,
        "title": "A task",
        "status": status,
    }
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


# ── set_task_status: succeeds given EACH ref form, PATCH hits resolved uuid ───


@respx.mock
async def test_set_task_status_uuid_form_no_resolve_http(server):
    """A UUID short-circuits resolve_ref (no resolve HTTP) and PATCHes directly."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123")
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123")
    patch = respx.patch(f"{BASE}/tasks/{TASK_UUID}").mock(
        return_value=httpx.Response(200, json=_env(_task(status="done")))
    )

    result = await _call(server, "set_task_status", task_id=TASK_UUID, status="done")
    out = json.loads(result)

    assert patch.called
    # UUID short-circuits: no resolve round-trip whatsoever.
    assert not by_seq.called
    assert not by_ref.called
    assert out["id"] == TASK_UUID
    assert out["status"] == "done"


@respx.mock
async def test_set_task_status_sequence_form(server):
    """``#123`` resolves via GET /items/by-seq/123, then PATCHes the resolved uuid."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "task"}))
    )
    patch = respx.patch(f"{BASE}/tasks/{TASK_UUID}").mock(
        return_value=httpx.Response(200, json=_env(_task(status="done")))
    )

    result = await _call(server, "set_task_status", task_id="#123", status="done")
    out = json.loads(result)

    assert by_seq.called and patch.called
    assert out["id"] == TASK_UUID


@respx.mock
async def test_set_task_status_canonical_form(server):
    """``acme-123`` resolves via GET /items/by-ref/acme-123, then PATCHes the uuid."""
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "task"}))
    )
    patch = respx.patch(f"{BASE}/tasks/{TASK_UUID}").mock(
        return_value=httpx.Response(200, json=_env(_task(status="done")))
    )

    result = await _call(
        server, "set_task_status", task_id="u-1y0e2v-123", status="done"
    )
    out = json.loads(result)

    assert by_ref.called and patch.called
    assert out["id"] == TASK_UUID


@respx.mock
async def test_set_task_status_app_url_form(server):
    """An app URL with a sequence resolves by-REF (not by-seq), then PATCHes."""
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "task"}))
    )
    patch = respx.patch(f"{BASE}/tasks/{TASK_UUID}").mock(
        return_value=httpx.Response(200, json=_env(_task(status="done")))
    )

    result = await _call(
        server,
        "set_task_status",
        task_id="https://app.defernowork.com/o/u-1y0e2v/items/123",
        status="done",
    )
    out = json.loads(result)

    assert by_ref.called and patch.called
    assert out["id"] == TASK_UUID


# ── set_task_status: resolution failures surface clearly, no PATCH issued ─────


@respx.mock
async def test_set_task_status_not_auto_routed_surfaces_400_and_skips_patch(server):
    """``ABC-223`` (uppercase alias) is not auto-routed -> DefernoError 400 locally.

    The mutation PATCH must NOT fire, and the returned string is a clear error.
    """
    patch = respx.patch(f"{BASE}/tasks/{TASK_UUID}").mock(
        return_value=httpx.Response(200, json=_env(_task(status="done")))
    )

    result = await _call(server, "set_task_status", task_id="ABC-223", status="done")

    assert isinstance(result, str)
    assert "400" in result
    # resolve_ref raises a code-less 400 -> rendered "Deferno API error 400: ..."
    assert "not an auto-routable" in result
    # The mutation must NOT have run against an unresolved ref.
    assert not patch.called


@respx.mock
async def test_set_task_status_not_found_surfaces_404(server):
    """``#999`` -> GET by-seq/999 returns 404; the not-found surfaces clearly."""
    respx.get(f"{BASE}/items/by-seq/999").mock(
        return_value=httpx.Response(
            404,
            json={
                "version": "0.2",
                "data": None,
                "error": {"code": "not_found", "message": "item not found"},
            },
        )
    )
    patch = respx.patch(f"{BASE}/tasks/{TASK_UUID}")

    result = await _call(server, "set_task_status", task_id="#999", status="done")

    assert isinstance(result, str)
    assert "404" in result
    assert "not_found" in result
    assert not patch.called


# ── move_item: kind-neutral; resolves BOTH ids; None new_parent_id passes through ─


@respx.mock
async def test_move_item_resolves_both_ids(server):
    """move_item resolves item_id AND a non-None new_parent_id before the move.

    Distinct seqs/refs for item vs parent keep the two resolves unambiguous; the
    POST path must use the resolved ITEM uuid and the body the resolved PARENT uuid.
    """
    by_seq_item = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "chore"}))
    )
    by_ref_parent = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-456").mock(
        return_value=httpx.Response(200, json=_env({"id": PARENT_UUID, "kind": "task"}))
    )
    move = respx.post(f"{BASE}/items/{TASK_UUID}/move").mock(
        return_value=httpx.Response(200, json=_env(_task()))
    )

    result = await _call(
        server,
        "move_item",
        item_id="#123",
        new_parent_id="u-1y0e2v-456",
        position=2,
    )
    json.loads(result)

    assert by_seq_item.called and by_ref_parent.called and move.called
    # POST path used the resolved ITEM uuid.
    assert move.calls.last.request.url.path == f"/api/items/{TASK_UUID}/move"
    # Body carried the resolved PARENT uuid + the position.
    body = json.loads(move.calls.last.request.content)
    assert body["new_parent_id"] == PARENT_UUID
    assert body["position"] == 2


@respx.mock
async def test_move_item_none_parent_is_root_detach_no_resolve(server):
    """new_parent_id=None means detach-to-root: kept None, never resolved.

    item_id is a non-UUID so exactly ONE resolve (by-seq) fires; the move body
    must carry ``new_parent_id: null``.
    """
    by_seq_item = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "event"}))
    )
    move = respx.post(f"{BASE}/items/{TASK_UUID}/move").mock(
        return_value=httpx.Response(200, json=_env(_task()))
    )

    result = await _call(server, "move_item", item_id="#123", new_parent_id=None)
    json.loads(result)

    assert by_seq_item.called and move.called
    body = json.loads(move.calls.last.request.content)
    assert body["new_parent_id"] is None


def test_move_task_retired_in_favor_of_move_item(server):
    with pytest.raises(LookupError):
        _tool(server, "move_task")


# ── update_task: resolves first; recurring-scope get_task uses the resolved uuid ─


@respx.mock
async def test_update_task_recurring_scope_check_uses_resolved_uuid(server):
    """A non-UUID ref resolves first; BOTH get_task (series check) and the PATCH
    run against the resolved UUID.

    The series check only fires for a deferno field (title here) with
    recurring_scope unset; the get_task body omits ``series_id`` so the flow
    proceeds to PATCH.
    """
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": TASK_UUID, "kind": "task"}))
    )
    get_task = respx.get(f"{BASE}/tasks/{TASK_UUID}").mock(
        return_value=httpx.Response(200, json=_env(_task()))
    )
    patch = respx.patch(f"{BASE}/tasks/{TASK_UUID}").mock(
        return_value=httpx.Response(200, json=_env(_task(title="renamed")))
    )

    result = await _call(server, "update_task", task_id="#123", title="renamed")
    out = json.loads(result)

    # Resolve happened, then BOTH get_task and PATCH hit the resolved uuid.
    assert by_seq.called and get_task.called and patch.called
    assert get_task.calls.last.request.url.path == f"/api/tasks/{TASK_UUID}"
    assert patch.calls.last.request.url.path == f"/api/tasks/{TASK_UUID}"
    assert out["title"] == "renamed"
