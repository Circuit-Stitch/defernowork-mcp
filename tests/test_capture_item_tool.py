"""respx integration for the capture_item tool: derive -> dispatch -> POST."""

from __future__ import annotations

import inspect
import json

import httpx
import pytest
import respx

from defernowork_mcp import server as srv
from defernowork_mcp.client import DefernoClient

BASE = "http://test:3000/api"
NEW_ID = "00000000-0000-0000-0000-000000000001"


def _env(data):
    return {"version": "0.2", "data": data, "error": None}


def _created(kind):
    return _env({"id": NEW_ID, "kind": kind, "title": "x", "status": "open"})


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
    return await _tool(mcp, name).fn(**kwargs)


@respx.mock
@pytest.mark.asyncio
async def test_task_minimal_posts_tasks(server):
    route = respx.post(f"{BASE}/tasks").mock(
        return_value=httpx.Response(201, json=_created("task"))
    )
    out = await _call(server, "capture_item", title="Buy milk", attend=False, repeats=False)
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"title": "Buy milk"}  # nulls omitted, no recurrence key
    assert json.loads(out)["id"] == NEW_ID


@respx.mock
@pytest.mark.asyncio
async def test_event_passes_complete_by_through_and_maps_start_tod(server):
    route = respx.post(f"{BASE}/events").mock(
        return_value=httpx.Response(201, json=_created("event"))
    )
    await _call(
        server, "capture_item", title="Call", attend=True, repeats=False,
        complete_by="2026-07-01T16:00:00Z", time_of_day="09:30",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["complete_by"] == "2026-07-01T16:00:00Z"  # passed through verbatim
    assert body["start_time_of_day"] == "09:30"
    assert "deadline_time_of_day" not in body


@respx.mock
@pytest.mark.asyncio
async def test_need_posts_chores(server):
    route = respx.post(f"{BASE}/chores").mock(
        return_value=httpx.Response(201, json=_created("chore"))
    )
    await _call(
        server, "capture_item", title="Trash", attend=False, repeats=True,
        obligation="need", recurrence={"type": "weekly", "days": ["Tue"]},
        complete_by="2026-06-23T16:00:00Z", time_of_day="20:00",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["recurrence"] == {"type": "weekly", "days": ["Tue"]}
    assert body["complete_by"] == "2026-06-23T16:00:00Z"
    assert body["deadline_time_of_day"] == "20:00"


@respx.mock
@pytest.mark.asyncio
async def test_want_posts_habits(server):
    route = respx.post(f"{BASE}/habits").mock(
        return_value=httpx.Response(201, json=_created("habit"))
    )
    await _call(
        server, "capture_item", title="Stretch", attend=False, repeats=True,
        obligation="want", recurrence={"type": "daily"},
    )
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["recurrence"] == {"type": "daily"}


@respx.mock
@pytest.mark.asyncio
async def test_validation_error_short_circuits_before_post(server):
    route = respx.post(f"{BASE}/events").mock(
        return_value=httpx.Response(201, json=_created("event"))
    )
    out = await _call(server, "capture_item", title="Meeting", attend=True, repeats=False)
    assert not route.called  # no complete_by -> derive raises before any HTTP call
    assert "complete_by" in out


def test_capture_item_has_no_parent_id_param(server):
    sig = inspect.signature(_tool(server, "capture_item").fn)
    assert "parent_id" not in sig.parameters  # ADR-0003: parent_id is create_task-only


@pytest.mark.parametrize("removed", ["create_chore", "create_habit", "create_event"])
def test_per_kind_create_tools_removed(server, removed):
    with pytest.raises(LookupError):
        _tool(server, removed)
