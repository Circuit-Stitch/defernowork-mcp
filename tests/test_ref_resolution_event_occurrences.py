"""Transparent ref resolution wiring for event_occurrences.py (issue #7 part D).

Part A's tests/test_ref_resolution_tasks.py carries the heavy per-form matrix.
This file is the light per-file proof that the 11 event_occurrences tools resolve
``event_id`` (the parent Event identifier) before acting:

- a non-UUID ``event_id`` resolves before the occurrence op hits the resolved-uuid
  ``/events/{uuid}/...`` path; a UUID short-circuits with no resolve HTTP.
- ``delete_event_occurrence_attachment`` resolves ``event_id`` but passes ``att_id``
  through verbatim (att_id is an attachment id, not an item Ref input form).
- a NOT_AUTO_ROUTED ref surfaces a clear error and issues NO operation.

Tools are exercised through the public interface: a real FastMCP server built by
``create_server`` (client pointed at a respx-mocked backend), the tool looked up
from the registry and invoked.
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
DATE = "2026-06-03"


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


# ── non-UUID event_id resolves, then the op hits the resolved-uuid path ───────


@respx.mock
async def test_reschedule_event_occurrence_sequence_form_resolves_then_acts(server):
    """``#123`` resolves via GET /items/by-seq/123, then POSTs the reschedule on
    the RESOLVED-uuid event path."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    reschedule = respx.post(
        f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}/reschedule"
    ).mock(
        return_value=httpx.Response(
            200, json=_env({"scheduled_date": "2026-06-10", "status": "Scheduled"})
        )
    )

    result = await _call(
        server,
        "reschedule_event_occurrence",
        event_id="#123",
        date=DATE,
        new_date="2026-06-10",
    )
    out = json.loads(result)

    assert by_seq.called and reschedule.called
    assert (
        reschedule.calls.last.request.url.path
        == f"/api/events/{ITEM_UUID}/occurrences/{DATE}/reschedule"
    )
    assert out["status"] == "Scheduled"


@respx.mock
async def test_set_event_occurrence_uuid_form_no_resolve_http(server):
    """A UUID short-circuits resolve_ref (no resolve HTTP) and POSTs directly."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123")
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123")
    set_occ = respx.post(f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}").mock(
        return_value=httpx.Response(
            200,
            json=_env(
                {
                    "id": "00000000-0000-0000-0000-000000000001",
                    "parent_id": ITEM_UUID,
                    "scheduled_date": DATE,
                    "status": "DoneOnTime",
                }
            ),
        )
    )

    result = await _call(
        server, "set_event_occurrence", event_id=ITEM_UUID, date=DATE, action="done"
    )
    out = json.loads(result)

    assert set_occ.called
    # UUID short-circuits: no resolve round-trip whatsoever.
    assert not by_seq.called
    assert not by_ref.called
    assert (
        set_occ.calls.last.request.url.path
        == f"/api/events/{ITEM_UUID}/occurrences/{DATE}"
    )
    assert out["status"] == "DoneOnTime"


# ── delete_event_occurrence_attachment: resolve event_id, pass att_id verbatim ─


@respx.mock
async def test_delete_event_occurrence_attachment_resolves_event_id_passes_att_id(
    server,
):
    """``acme-123`` event_id resolves via by-ref; a non-routable ``att_id`` rides
    through verbatim as the final path segment.

    ``att_xyz`` deliberately classifies NOT_AUTO_ROUTED (no hyphen-digit / uuid
    shape): if att_id were ever fed to resolve_ref it would 400 locally and the
    DELETE would never fire, so a successful DELETE proves att_id is unresolved.
    """
    att_id = "att_xyz"
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    delete = respx.delete(
        f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}/attachments/{att_id}"
    ).mock(return_value=httpx.Response(204))

    result = await _call(
        server,
        "delete_event_occurrence_attachment",
        event_id="u-1y0e2v-123",
        date=DATE,
        att_id=att_id,
    )
    out = json.loads(result)

    assert by_ref.called and delete.called
    # event_id resolved to the uuid; att_id passed through verbatim.
    assert (
        delete.calls.last.request.url.path
        == f"/api/events/{ITEM_UUID}/occurrences/{DATE}/attachments/{att_id}"
    )
    assert out == {"ok": True}


# ── resolution failure: clear error, NO operation issued ──────────────────────


@respx.mock
async def test_set_event_occurrence_not_auto_routed_surfaces_400_and_skips_op(server):
    """``ABC-223`` (uppercase alias) is not auto-routed -> DefernoError 400 locally.

    The occurrence POST must NOT fire, and the returned string is a clear error.
    """
    set_occ = respx.post(f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}").mock(
        return_value=httpx.Response(200, json=_env({"status": "DoneOnTime"}))
    )

    result = await _call(
        server, "set_event_occurrence", event_id="ABC-223", date=DATE, action="done"
    )

    assert isinstance(result, str)
    assert "400" in result
    assert "not an auto-routable" in result
    # The operation must NOT have run against an unresolved ref.
    assert not set_occ.called
