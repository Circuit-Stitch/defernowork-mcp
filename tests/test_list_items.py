"""Behavioural tests for ``list_items`` — client method + MCP tool.

Exercised through the public interface with a respx-mocked backend:

- The CLIENT layer (``DefernoClient.list_items``) is asserted on the OUTGOING
  request query it builds: ``$select`` (the compact field set), ``$top``,
  ``$filter`` (composed from kind / status / from_date / to_date), and the
  ``window`` opt-out. The client returns the backend rows verbatim.
- The TOOL layer (``list_items`` via ``create_server``) is asserted on the
  RETURNED rows: Compact-by-default projection vs ``full=true`` untouched, and
  that a backend 400 surfaces through ``format_error`` (not swallowed).

Backend contract pinned by reading the Rust source (verified, not guessed):

- Filterable field names: ``kind`` (NOT ``type``), ``status``, and the date
  field is ``complete_by`` — a *DateTime* field. The OData evaluator has no
  Date<->DateTime coercion (odata.rs ``compare``), so a bare ``YYYY-MM-DD``
  literal would tokenize to ``Literal::Date`` and match ZERO DateTime rows.
  ``from_date`` / ``to_date`` are therefore widened to RFC3339 day boundaries
  (``ge {d}T00:00:00Z`` / ``le {d}T23:59:59.999Z``), mirroring how the webui's
  ``buildVisibilityFilter`` composes ``complete_by gt {ISO datetime}``.
- ``$top`` is REJECTED (400 ``$top exceeds max of 500``) when above 500 — it is
  NOT silently clamped (odata.rs ``parse_top``). The client passes ``limit``
  through verbatim; the caller gets the clear 400 via ``format_error``.
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import respx

from defernowork_mcp import server as srv
from defernowork_mcp.client import DefernoClient, DefernoError

BASE = "http://test:3000/api"

# A backend row carrying both the discriminators + envelope-injected fields the
# handler always adds (ref/org_slug/type/sequence), plus a heavy field the
# compact projection must drop.
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
    # heavy field that compact must drop:
    "description": "the body",
}


def _env(data):
    return {"version": "0.2", "data": data, "error": None}


def _query_of(request) -> dict[str, list[str]]:
    """Decoded query dict of the last captured request (lists per RFC3986)."""
    return parse_qs(urlsplit(str(request.url)).query, keep_blank_values=True)


# ── client layer: outgoing-request query construction ────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_client_default_sends_compact_select_and_no_filter():
    route = respx.get(f"{BASE}/items").mock(
        return_value=httpx.Response(200, json=_env([ROW]))
    )
    async with DefernoClient(base_url=BASE, token="t") as client:
        rows = await client.list_items()

    assert route.called
    q = _query_of(respx.calls.last.request)
    # $select carries exactly the compact LIST-row field set (order preserved).
    assert q["$select"] == ["kind,type,ref,title,status,complete_by,parent_id,labels"]
    # No filter, no top, no window by default.
    assert "$filter" not in q
    assert "$top" not in q
    assert "window" not in q
    # Client returns rows verbatim.
    assert rows == [ROW]


@respx.mock
@pytest.mark.asyncio
async def test_client_limit_maps_to_top():
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items(limit=25)
    q = _query_of(respx.calls.last.request)
    assert q["$top"] == ["25"]


@respx.mock
@pytest.mark.asyncio
async def test_client_limit_above_cap_passed_through_verbatim():
    # The backend caps $top at 500 by REJECTING with 400 (not clamping). The
    # client must pass the caller's number through unchanged.
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items(limit=999)
    q = _query_of(respx.calls.last.request)
    assert q["$top"] == ["999"]


@respx.mock
@pytest.mark.asyncio
async def test_client_full_drops_select():
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([ROW])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items(full=True)
    q = _query_of(respx.calls.last.request)
    assert "$select" not in q


@respx.mock
@pytest.mark.asyncio
async def test_client_window_all_sends_opt_out():
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items(window="all")
    q = _query_of(respx.calls.last.request)
    assert q["window"] == ["all"]


@respx.mock
@pytest.mark.asyncio
async def test_client_window_default_omits_flag():
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items()
    q = _query_of(respx.calls.last.request)
    assert "window" not in q


# ── client layer: $filter composition ───────────────────────────────────────


@respx.mock
@pytest.mark.asyncio
async def test_client_kind_filter():
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items(kind="habit")
    q = _query_of(respx.calls.last.request)
    assert q["$filter"] == ["kind eq 'habit'"]


@respx.mock
@pytest.mark.asyncio
async def test_client_status_filter():
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items(status="open")
    q = _query_of(respx.calls.last.request)
    assert q["$filter"] == ["status eq 'open'"]


@respx.mock
@pytest.mark.asyncio
async def test_client_from_date_uses_datetime_lower_boundary():
    # complete_by is a DateTime field; from_date must widen to a start-of-day
    # RFC3339 instant, never a bare YYYY-MM-DD (which matches zero rows).
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items(from_date="2026-06-01")
    q = _query_of(respx.calls.last.request)
    assert q["$filter"] == ["complete_by ge 2026-06-01T00:00:00Z"]


@respx.mock
@pytest.mark.asyncio
async def test_client_to_date_uses_datetime_upper_boundary():
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items(to_date="2026-06-30")
    q = _query_of(respx.calls.last.request)
    assert q["$filter"] == ["complete_by le 2026-06-30T23:59:59.999Z"]


@respx.mock
@pytest.mark.asyncio
async def test_client_composes_all_filters_with_and():
    respx.get(f"{BASE}/items").mock(return_value=httpx.Response(200, json=_env([])))
    async with DefernoClient(base_url=BASE, token="t") as client:
        await client.list_items(
            kind="task",
            status="open",
            from_date="2026-06-01",
            to_date="2026-06-30",
        )
    q = _query_of(respx.calls.last.request)
    assert q["$filter"] == [
        "kind eq 'task' and status eq 'open' "
        "and complete_by ge 2026-06-01T00:00:00Z "
        "and complete_by le 2026-06-30T23:59:59.999Z"
    ]


# ── tool layer: compact-by-default vs full, error surfacing ──────────────────


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


@respx.mock
@pytest.mark.asyncio
async def test_tool_compact_by_default(server):
    respx.get(f"{BASE}/items").mock(
        return_value=httpx.Response(200, json=_env([ROW]))
    )
    out = json.loads(await _tool(server, "list_items").fn())
    assert isinstance(out, list) and len(out) == 1
    row = out[0]
    # Compact LIST-row whitelist present...
    for k in ("kind", "type", "ref", "title", "status", "complete_by", "parent_id", "labels"):
        assert k in row
    # ...and the body (description) plus raw id are dropped from list rows.
    assert "description" not in row
    assert "id" not in row


@respx.mock
@pytest.mark.asyncio
async def test_tool_full_returns_rows_untouched(server):
    respx.get(f"{BASE}/items").mock(
        return_value=httpx.Response(200, json=_env([ROW]))
    )
    out = json.loads(await _tool(server, "list_items").fn(full=True))
    assert out == [ROW]


@respx.mock
@pytest.mark.asyncio
async def test_tool_window_all_opts_out(server):
    route = respx.get(f"{BASE}/items").mock(
        return_value=httpx.Response(200, json=_env([]))
    )
    await _tool(server, "list_items").fn(window="all")
    assert route.called
    q = _query_of(respx.calls.last.request)
    assert q["window"] == ["all"]


@respx.mock
@pytest.mark.asyncio
async def test_tool_unknown_filter_field_400_surfaces(server):
    # The backend rejects an unfilterable field with 400; the tool must surface
    # it via format_error, NOT swallow it. (We can only reach this path by
    # mocking the backend response — kind/status/complete_by are all allowlisted.)
    respx.get(f"{BASE}/items").mock(
        return_value=httpx.Response(
            400,
            json={
                "version": "0.2",
                "data": None,
                "error": {"code": "bad_request", "message": "field 'nope' not filterable"},
            },
        )
    )
    result = await _tool(server, "list_items").fn(status="open")
    assert isinstance(result, str)
    assert "400" in result
    assert "not filterable" in result
