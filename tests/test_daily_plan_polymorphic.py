"""``get_daily_plan`` must read the kind-polymorphic plan feed.

Regression tests for the bug where the tool read ``GET /tasks/plan``. That
backend handler filters the plan's id list through ``load_tasks_by_ids`` and
``filter_map``s the misses away, so every Habit, Chore, and Event on the plan
is **silently dropped** — a user whose whole day is a habit gets ``[]`` back,
while the tool's docstring and the server instructions both promise otherwise.

``GET /items/plan`` is the same seeder over the same plan id list, but returns
a kind-tagged union (``kind`` = ``task`` | ``habit`` | ``chore`` | ``event``),
and the recurring variants carry ``today_occurrence`` — the only field that can
answer "is this done today?", since a recurring item's ``status`` is
``active``/``archived`` and can never be ``done``.

Wire shape verified against the Rust source, not guessed:
``backend/src/repository/daily_plan.rs`` (``DailyPlanItem``, a serde
``tag = "kind"``, ``rename_all = "snake_case"`` union whose Habit/Chore/Event
variants flatten the entity and add ``today_occurrence``) and
``backend/src/handlers/items_plan.rs::get_daily_plan_items`` (wraps each row in
``ItemEnvelope::new_with_inner_kind``, which stamps ``ref`` / ``org_slug`` /
``sequence`` / ``type`` and deliberately omits its own ``kind`` so the union's
tag is not duplicated).
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from defernowork_mcp import server as srv
from defernowork_mcp.client import DefernoClient

BASE = "http://test:3000/api"

TASK_ROW = {
    "kind": "task",
    "type": "task",
    "id": "11111111-1111-1111-1111-111111111111",
    "ref": "u-1y0e2v-1",
    "org_slug": "u-1y0e2v",
    "sequence": 1,
    "title": "Write the classifier",
    "status": "open",
    "complete_by": "2026-08-03T00:00:00Z",
}

HABIT_ROW = {
    "kind": "habit",
    "type": "habit",
    "id": "22222222-2222-2222-2222-222222222222",
    "ref": "u-1y0e2v-2",
    "org_slug": "u-1y0e2v",
    "sequence": 2,
    "title": "Standup",
    "status": "active",
    "complete_by": "2026-08-04T00:00:00Z",
    "today_occurrence": {
        "id": "33333333-3333-3333-3333-333333333333",
        "parent_id": "22222222-2222-2222-2222-222222222222",
        "scheduled_date": "2026-08-03",
        "complete_by": "2026-08-03T23:59:59Z",
        "status": "done_on_time",
        "done_at": "2026-08-03T09:15:00Z",
    },
}

CHORE_ROW = {
    "kind": "chore",
    "type": "chore",
    "id": "44444444-4444-4444-4444-444444444444",
    "ref": "u-1y0e2v-3",
    "org_slug": "u-1y0e2v",
    "sequence": 3,
    "title": "Take out the bins",
    "status": "active",
    "today_occurrence": {
        "id": "55555555-5555-5555-5555-555555555555",
        "parent_id": "44444444-4444-4444-4444-444444444444",
        "scheduled_date": "2026-08-03",
        "complete_by": "2026-08-03T23:59:59Z",
        "status": "scheduled",
    },
}

EVENT_ROW = {
    "kind": "event",
    "type": "event",
    "id": "66666666-6666-6666-6666-666666666666",
    "ref": "u-1y0e2v-4",
    "org_slug": "u-1y0e2v",
    "sequence": 4,
    "title": "Dentist",
    "status": "active",
    "today_occurrence": {
        "id": "77777777-7777-7777-7777-777777777777",
        "parent_id": "66666666-6666-6666-6666-666666666666",
        "scheduled_date": "2026-08-03",
        "complete_by": "2026-08-03T23:59:59Z",
        "status": "dropped",
    },
}

PLAN = [TASK_ROW, HABIT_ROW, CHORE_ROW, EVENT_ROW]


def _env(data):
    return {"version": "0.2", "data": data, "error": None}


def _query_of(request) -> dict[str, list[str]]:
    return parse_qs(urlsplit(str(request.url)).query, keep_blank_values=True)


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


# ── client layer: which endpoint is actually called ──────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_client_get_daily_plan_reads_the_items_plan_feed():
    route = respx.get(f"{BASE}/items/plan").mock(
        return_value=httpx.Response(200, json=_env(PLAN))
    )
    async with DefernoClient(base_url=BASE, token="t") as client:
        rows = await client.get_daily_plan()

    assert route.called, "get_daily_plan must read /items/plan, not /tasks/plan"
    assert [r["kind"] for r in rows] == ["task", "habit", "chore", "event"]


@respx.mock
@pytest.mark.asyncio
async def test_client_get_daily_plan_keeps_date_and_tz_query_params():
    route = respx.get(url__startswith=f"{BASE}/items/plan").mock(
        return_value=httpx.Response(200, json=_env([]))
    )
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.get_daily_plan("2026-08-03", tz="America/Los_Angeles")

    assert route.called
    query = _query_of(respx.calls.last.request)
    assert query["date"] == ["2026-08-03"]
    assert query["tz"] == ["America/Los_Angeles"]


@respx.mock
@pytest.mark.asyncio
async def test_client_get_daily_plan_never_touches_tasks_plan():
    """The Task-only endpoint must not be reachable from this client method."""
    items_plan = respx.get(url__startswith=f"{BASE}/items/plan").mock(
        return_value=httpx.Response(200, json=_env(PLAN))
    )
    tasks_plan = respx.get(url__startswith=f"{BASE}/tasks/plan").mock(
        return_value=httpx.Response(200, json=_env([TASK_ROW]))
    )
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.get_daily_plan()

    assert items_plan.called
    assert not tasks_plan.called, "/tasks/plan silently drops Habits/Chores/Events"


# ── tool layer: non-Task plan members survive to the agent ───────────────────


@respx.mock
@pytest.mark.asyncio
async def test_tool_returns_habits_chores_and_events(server):
    respx.get(url__startswith=f"{BASE}/items/plan").mock(
        return_value=httpx.Response(200, json=_env(PLAN))
    )
    out = json.loads(await _tool(server, "get_daily_plan").fn())

    assert [row["kind"] for row in out] == ["task", "habit", "chore", "event"]
    assert {row["title"] for row in out} == {
        "Write the classifier",
        "Standup",
        "Take out the bins",
        "Dentist",
    }


@respx.mock
@pytest.mark.asyncio
async def test_tool_row_carries_today_occurrence_status(server):
    """An agent must be able to tell a checked-in Habit from an open one.

    The Habit's item ``status`` is ``active`` on both a done and an undone day;
    only ``today_occurrence.status`` distinguishes them.
    """
    respx.get(url__startswith=f"{BASE}/items/plan").mock(
        return_value=httpx.Response(200, json=_env(PLAN))
    )
    out = json.loads(await _tool(server, "get_daily_plan").fn())
    by_kind = {row["kind"]: row for row in out}

    assert by_kind["habit"]["status"] == "active"
    assert by_kind["habit"]["today_occurrence"]["status"] == "done_on_time"
    assert by_kind["chore"]["today_occurrence"]["status"] == "scheduled"
    assert by_kind["event"]["today_occurrence"]["status"] == "dropped"
    # A Task has no per-day occurrence — its own status is the answer.
    assert "today_occurrence" not in by_kind["task"]


@respx.mock
@pytest.mark.asyncio
async def test_tool_forwards_date_and_tz(server):
    respx.get(url__startswith=f"{BASE}/items/plan").mock(
        return_value=httpx.Response(200, json=_env([]))
    )
    await _tool(server, "get_daily_plan").fn(
        date="2026-08-03", tz="America/Los_Angeles"
    )

    query = _query_of(respx.calls.last.request)
    assert query["date"] == ["2026-08-03"]
    assert query["tz"] == ["America/Los_Angeles"]


# ── resource layer: the plan resource rides the same client method ───────────


@respx.mock
@pytest.mark.asyncio
async def test_plan_resource_serves_the_polymorphic_feed(server):
    respx.get(url__startswith=f"{BASE}/items/plan").mock(
        return_value=httpx.Response(200, json=_env(PLAN))
    )
    resource = await server.read_resource("defernowork://tasks/plan")
    payload = json.loads(list(resource)[0].content)

    assert [row["kind"] for row in payload] == ["task", "habit", "chore", "event"]
