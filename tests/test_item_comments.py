"""Kind-neutral item-level COMMENT tools (issue #12).

Scope of what the MCP owns and these tests verify:
- a ref (any input form) is resolved to a UUID, then the comment call hits the
  item-level path ``/items/{id}/comments`` with the right body;
- a backend error (e.g. the 400 an Event gets) is surfaced, not swallowed.

What the MCP only FORWARDS (backend behavior, mocked here, NOT MCP logic):
- **kind-neutrality** — ``POST /items/{id}/comments`` accepts Task today and
  Chore/Habit once Deferno backend **#266** lands. Until then the live path is
  Task-only (Deferno router_tests.rs documents this), so the Chore/Habit cases
  below are MOCKED CONTRACT, unverifiable end-to-end until #266 ships.
- **Event rejection** — the backend 400s an item-level comment on an Event; the
  MCP's contribution is the docstring redirect to the per-occurrence tools. The
  400-passthrough test is generic (the mock doesn't know the kind) and stands as
  contract documentation, not Event-specific proof.

i.e. *suite-green here means "the MCP behaves correctly against the mocked
contract", not "the feature works end-to-end."*
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


# ── post_item_comment ─────────────────────────────────────────────────────────


@respx.mock
async def test_post_item_comment_resolves_ref_then_posts(server):
    """A sequence ref resolves, then POSTs the body to the resolved item path."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "chore"}))
    )
    post = respx.post(f"{BASE}/items/{ITEM_UUID}/comments").mock(
        return_value=httpx.Response(
            201, json=_env({"id": "c1", "body": "hi", "is_private": False})
        )
    )

    result = await _call(server, "post_item_comment", item_id="#123", body="hi")
    out = json.loads(result)

    assert by_seq.called and post.called
    body = json.loads(post.calls.last.request.content)
    assert body == {"body": "hi", "is_private": False}
    assert out["id"] == "c1"


@respx.mock
async def test_post_item_comment_uuid_passes_is_private(server):
    """A raw UUID needs no by-seq/by-ref resolve, but the kind-dispatching tool
    issues one GET /items/{id} to learn the kind, then POSTs the comment."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123")
    get = respx.get(f"{BASE}/items/{ITEM_UUID}").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "task"}))
    )
    post = respx.post(f"{BASE}/items/{ITEM_UUID}/comments").mock(
        return_value=httpx.Response(201, json=_env({"id": "c1"}))
    )

    await _call(
        server, "post_item_comment", item_id=ITEM_UUID, body="secret", is_private=True
    )

    assert post.called
    assert get.called  # resolve_ref_with_kind learns the kind via GET /items/{id}
    assert not by_seq.called  # no by-seq/by-ref resolve for a raw UUID
    body = json.loads(post.calls.last.request.content)
    assert body == {"body": "secret", "is_private": True}


# ── post_item_comment: Event ref + date routes to the per-occurrence path ──────


DATE = "2026-06-03"


@respx.mock
async def test_post_item_comment_event_with_date_routes_to_occurrence(server):
    """An Event ref + ``date`` posts to /events/{id}/occurrences/{date}/comment,
    NOT the item-level /items/{id}/comments path."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    occ_post = respx.post(
        f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}/comment"
    ).mock(return_value=httpx.Response(201, json=_env({"id": "c1", "body": "hi"})))
    item_post = respx.post(f"{BASE}/items/{ITEM_UUID}/comments")

    result = await _call(
        server, "post_item_comment", item_id="#123", body="hi", date=DATE
    )
    out = json.loads(result)

    assert by_seq.called and occ_post.called
    assert not item_post.called  # event+date does NOT hit the item-level path
    body = json.loads(occ_post.calls.last.request.content)
    assert body == {"body": "hi", "is_private": False}
    assert out["id"] == "c1"


@respx.mock
async def test_post_item_comment_event_without_date_hits_item_level(server):
    """An Event ref with NO date still hits /items/{id}/comments — the backend
    400s there, but that routing is the MCP's documented no-date behavior."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    item_post = respx.post(f"{BASE}/items/{ITEM_UUID}/comments").mock(
        return_value=httpx.Response(201, json=_env({"id": "c1"}))
    )
    occ_post = respx.post(f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}/comment")

    await _call(server, "post_item_comment", item_id="#123", body="hi")

    assert by_seq.called and item_post.called
    assert not occ_post.called  # no date -> no per-occurrence routing


@respx.mock
async def test_post_item_comment_surfaces_backend_400(server):
    """Contract-documentation passthrough: a backend 4xx (e.g. the 400 an Event
    gets on the item-level path) is surfaced, not swallowed. The mock is generic
    — it documents the passthrough, not Event-specific behavior."""
    respx.get(f"{BASE}/items/by-seq/9").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    respx.post(f"{BASE}/items/{ITEM_UUID}/comments").mock(
        return_value=httpx.Response(
            400,
            json={
                "version": "0.2",
                "data": None,
                "error": {
                    "code": "bad_request",
                    "message": "item-level comments are not supported for Event",
                },
            },
        )
    )

    result = await _call(server, "post_item_comment", item_id="#9", body="hi")

    assert isinstance(result, str)
    assert "400" in result
    assert "not supported for Event" in result


# ── list_item_comments ────────────────────────────────────────────────────────


@respx.mock
async def test_list_item_comments_resolves_ref_then_gets(server):
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "habit"}))
    )
    get = respx.get(f"{BASE}/items/{ITEM_UUID}/comments").mock(
        return_value=httpx.Response(200, json=_env([{"id": "c1"}, {"id": "c2"}]))
    )

    result = await _call(server, "list_item_comments", item_id="u-1y0e2v-123")
    out = json.loads(result)

    assert by_ref.called and get.called
    assert [c["id"] for c in out] == ["c1", "c2"]
