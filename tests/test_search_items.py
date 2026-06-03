"""Behavioural tests for the ``search_items`` MCP tool (issue #5).

``search_items`` is the compact, kind-neutral replacement for ``search_tasks``.
It reuses the existing ``DefernoClient.search_tasks`` path (``GET /tasks/search``)
-- full-text is Tasks-only in the backend today -- but returns a **Compact**
projection (the same ``COMPACT_ITEM_CORE_FIELDS`` list-row set ``list_items``
uses) by default, with ``full=true`` returning the rows verbatim. The previous
filter set (status / label / from_date / to_date / parent_id) is preserved.

These are bespoke respx-mocked tests through the tool's public interface:

- compact-by-default row shape: ``ref`` survives the projection, the heavy
  body (``description``) and raw ``id`` are dropped;
- ``full=true`` returns the enveloped rows untouched;
- the full filter set is forwarded to the backend search query. NOTE: unlike
  ``list_items`` (which widens dates to RFC3339 day boundaries for an OData
  ``$filter``), ``search_tasks`` forwards ``from_date`` / ``to_date`` VERBATIM
  as the bare wire params ``from`` / ``to`` (see ``client.search_tasks``), so
  the assertions below pin the un-widened ``YYYY-MM-DD`` values and the wire
  names ``q`` / ``status`` / ``label`` / ``from`` / ``to`` / ``parent_id``;
- the ``query`` arg is required and forwarded as ``q``.
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

# A FULL enveloped search row: the backend search handler returns
# Versioned<Vec<ItemEnvelope<TaskSummary>>>, so each row carries the identity
# fields (ref/org_slug/type/sequence) exactly like a /items list row, plus the
# heavy fields (id/description) the compact projection must drop.
ROW = {
    "kind": "task",
    "type": "task",
    "id": "11111111-2222-3333-4444-555555555555",
    "ref": "u-1y0e2v-123",
    "sequence": 123,
    "org_slug": "u-1y0e2v",
    "title": "Write the classifier",
    "status": "open",
    "complete_by": "2026-06-10T00:00:00Z",
    "parent_id": None,
    "labels": ["mcp"],
    # heavy fields the compact projection must drop:
    "description": "the body",
}


def _env(data):
    return {"version": "0.2", "data": data, "error": None}


def _query_of(request) -> dict[str, list[str]]:
    """Decoded query dict of the captured request (lists per RFC3986)."""
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


# ── compact-by-default vs full ───────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_tool_compact_by_default(server):
    respx.get(f"{BASE}/tasks/search").mock(
        return_value=httpx.Response(200, json=_env([ROW]))
    )
    out = json.loads(await _tool(server, "search_items").fn(query="classifier"))
    assert isinstance(out, list) and len(out) == 1
    row = out[0]
    # Compact LIST-row whitelist present (identifier + discriminator survive)...
    for k in (
        "kind",
        "type",
        "ref",
        "title",
        "status",
        "complete_by",
        "parent_id",
        "labels",
    ):
        assert k in row
    # ...and the body (description) plus raw id are dropped from compact rows.
    assert "description" not in row
    assert "id" not in row


@respx.mock
@pytest.mark.asyncio
async def test_tool_full_returns_rows_untouched(server):
    respx.get(f"{BASE}/tasks/search").mock(
        return_value=httpx.Response(200, json=_env([ROW]))
    )
    out = json.loads(
        await _tool(server, "search_items").fn(query="classifier", full=True)
    )
    assert out == [ROW]


# ── query + filter forwarding ────────────────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_tool_query_forwarded_as_q(server):
    route = respx.get(f"{BASE}/tasks/search").mock(
        return_value=httpx.Response(200, json=_env([]))
    )
    await _tool(server, "search_items").fn(query="groceries")
    assert route.called
    q = _query_of(respx.calls.last.request)
    assert q["q"] == ["groceries"]


@respx.mock
@pytest.mark.asyncio
async def test_tool_full_filter_set_forwarded_verbatim(server):
    # search_tasks forwards from_date/to_date VERBATIM as the bare wire params
    # from/to (NO RFC3339 widening, unlike list_items). Pin that here.
    route = respx.get(f"{BASE}/tasks/search").mock(
        return_value=httpx.Response(200, json=_env([]))
    )
    await _tool(server, "search_items").fn(
        query="report",
        status="open",
        label="mcp",
        from_date="2026-06-01",
        to_date="2026-06-30",
        parent_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    )
    assert route.called
    q = _query_of(respx.calls.last.request)
    assert q["q"] == ["report"]
    assert q["status"] == ["open"]
    assert q["label"] == ["mcp"]
    # Bare YYYY-MM-DD, NOT widened to a datetime boundary.
    assert q["from"] == ["2026-06-01"]
    assert q["to"] == ["2026-06-30"]
    assert q["parent_id"] == ["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]


@respx.mock
@pytest.mark.asyncio
async def test_tool_omits_unset_filters(server):
    # With only query, none of the optional filter params should appear on the
    # wire (search_tasks only adds a param when its value is not None).
    route = respx.get(f"{BASE}/tasks/search").mock(
        return_value=httpx.Response(200, json=_env([]))
    )
    await _tool(server, "search_items").fn(query="solo")
    assert route.called
    q = _query_of(respx.calls.last.request)
    assert q["q"] == ["solo"]
    for absent in ("status", "label", "from", "to", "parent_id"):
        assert absent not in q
