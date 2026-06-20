"""respx integration for the kind-neutral occurrence tools (fix #3b).

Each tool resolves the item's kind from the ref and dispatches to the per-kind
backend endpoint. A non-UUID ref learns the kind from its resolve round-trip; a
raw UUID pays one GET /items/{id}.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from defernowork_mcp import server as srv
from defernowork_mcp.client import DefernoClient

BASE = "http://test:3000/api"
UUID = "11111111-2222-3333-4444-555555555555"


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
    return await _tool(mcp, name).fn(**kwargs)


def _by_seq(kind):
    return respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": UUID, "kind": kind}))
    )


# ── list_occurrences: dispatch by kind ────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,path",
    [
        ("chore", f"/chores/{UUID}/occurrences"),
        ("habit", f"/habits/{UUID}/occurrences"),
        ("event", f"/events/{UUID}/occurrences"),
    ],
)
async def test_list_occurrences_dispatches_by_kind(server, kind, path):
    _by_seq(kind)
    listing = respx.get(f"{BASE}{path}").mock(
        return_value=httpx.Response(200, json=_env([{"scheduled_date": "2026-06-03"}]))
    )
    out = await _call(server, "list_occurrences", ref="#123", from_date="2026-06-01")
    assert listing.called
    assert listing.calls.last.request.url.path == f"/api{path}"
    assert json.loads(out) == [{"scheduled_date": "2026-06-03"}]


# ── set_occurrence_status: per-kind native mapping ────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_set_status_chore_puts_status(server):
    _by_seq("chore")
    put = respx.put(f"{BASE}/chores/{UUID}/occurrences/2026-06-03").mock(
        return_value=httpx.Response(200, json=_env({"status": "DoneOnTime"}))
    )
    await _call(server, "set_occurrence_status", ref="#123", date="2026-06-03", status="done")
    assert put.called
    assert json.loads(put.calls.last.request.content) == {"status": "done"}


@respx.mock
@pytest.mark.asyncio
async def test_set_status_event_posts_action_and_threads_cascade(server):
    _by_seq("event")
    post = respx.post(f"{BASE}/events/{UUID}/occurrences/2026-06-03").mock(
        return_value=httpx.Response(200, json=_env({"status": "Dropped"}))
    )
    await _call(
        server, "set_occurrence_status", ref="#123", date="2026-06-03",
        status="dropped", cascade_subtasks=True,
    )
    body = json.loads(post.calls.last.request.content)
    assert body == {"action": "dropped", "cascade_subtasks": True}


@respx.mock
@pytest.mark.asyncio
async def test_set_status_habit_done_marks_true(server):
    _by_seq("habit")
    post = respx.post(f"{BASE}/habits/{UUID}/occurrences").mock(
        return_value=httpx.Response(200, json=_env({"done": True}))
    )
    await _call(server, "set_occurrence_status", ref="#123", date="2026-06-03", status="done")
    assert json.loads(post.calls.last.request.content) == {"done": True, "date": "2026-06-03"}


@respx.mock
@pytest.mark.asyncio
async def test_set_status_habit_dropped_marks_not_done(server):
    _by_seq("habit")
    post = respx.post(f"{BASE}/habits/{UUID}/occurrences").mock(
        return_value=httpx.Response(200, json=_env({"done": False}))
    )
    await _call(server, "set_occurrence_status", ref="#123", date="2026-06-03", status="dropped")
    assert json.loads(post.calls.last.request.content) == {"done": False, "date": "2026-06-03"}


@respx.mock
@pytest.mark.asyncio
async def test_set_status_habit_in_progress_is_noop(server):
    _by_seq("habit")
    post = respx.post(f"{BASE}/habits/{UUID}/occurrences")
    out = await _call(
        server, "set_occurrence_status", ref="#123", date="2026-06-03", status="in_progress"
    )
    assert not post.called  # habits have no in-progress -> no backend call
    assert json.loads(out)["ok"] is True


@respx.mock
@pytest.mark.asyncio
async def test_set_status_rejects_unknown_status_before_resolve(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123")
    out = await _call(
        server, "set_occurrence_status", ref="#123", date="2026-06-03", status="bogus"
    )
    assert not by_seq.called  # validated before any resolve round-trip
    assert "in_progress, done, dropped" in out


# ── reschedule_occurrence ─────────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_reschedule_event_posts_new_date(server):
    _by_seq("event")
    post = respx.post(f"{BASE}/events/{UUID}/occurrences/2026-06-03/reschedule").mock(
        return_value=httpx.Response(200, json=_env({"scheduled_date": "2026-06-10"}))
    )
    await _call(
        server, "reschedule_occurrence", ref="#123", date="2026-06-03", new_date="2026-06-10"
    )
    assert json.loads(post.calls.last.request.content) == {"new_date": "2026-06-10"}


# ── raw UUID: one GET /items/{id} to learn kind, then dispatch ────────────────


@respx.mock
@pytest.mark.asyncio
async def test_raw_uuid_gets_kind_then_dispatches(server):
    get = respx.get(f"{BASE}/items/{UUID}").mock(
        return_value=httpx.Response(200, json=_env({"id": UUID, "kind": "chore"}))
    )
    put = respx.put(f"{BASE}/chores/{UUID}/occurrences/2026-06-03").mock(
        return_value=httpx.Response(200, json=_env({"status": "InProgress"}))
    )
    await _call(server, "set_occurrence_status", ref=UUID, date="2026-06-03", status="in_progress")
    assert get.called and put.called  # UUID had no kind locally -> one GET


# ── dateless next-mode: mark_next_chore_done folded into set_occurrence_status ─


@respx.mock
@pytest.mark.asyncio
async def test_set_status_dateless_chore_marks_next_done(server):
    _by_seq("chore")
    post = respx.post(f"{BASE}/chores/{UUID}/mark-next-done").mock(
        return_value=httpx.Response(200, json=_env({"date": "2026-05-01", "status": "DoneOnTime"}))
    )
    out = await _call(server, "set_occurrence_status", ref="#123", status="done")
    assert post.called  # no date -> earliest unresolved occurrence endpoint
    assert json.loads(post.calls.last.request.content) == {"status": "done"}
    assert json.loads(out) == {"date": "2026-05-01", "status": "DoneOnTime"}


@respx.mock
@pytest.mark.asyncio
async def test_set_status_dateless_non_chore_errors_without_backend(server):
    _by_seq("habit")
    post = respx.post(f"{BASE}/habits/{UUID}/occurrences")
    out = await _call(server, "set_occurrence_status", ref="#123", status="done")
    assert not post.called  # dateless next-mode is chore-only -> no backend call
    assert "only for Chore" in out


# ── the 11 per-kind occurrence tools are retired; so is mark_next_chore_done ───


@pytest.mark.parametrize(
    "removed",
    [
        "list_chore_occurrences", "set_chore_occurrence_status", "reschedule_chore_occurrence",
        "list_habit_occurrences", "mark_habit_occurrence", "clear_habit_occurrence",
        "reschedule_habit_occurrence",
        "list_event_occurrences", "set_event_occurrence", "delete_event_occurrence",
        "reschedule_event_occurrence",
        "mark_next_chore_done",
    ],
)
def test_per_kind_occurrence_tools_removed(server, removed):
    with pytest.raises(LookupError):
        _tool(server, removed)
