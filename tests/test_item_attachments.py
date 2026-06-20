"""Kind-neutral item-level ATTACHMENT tools (issue #12).

⚠️ ASSUMED-CONTRACT / BLOCKED ON BACKEND ⚠️
The ``/items/{id}/attachments/*`` routes do **not** exist in the Deferno
backend yet — they land with Deferno backend **#215**. The shapes pinned here
MIRROR the existing per-Task surface (``/tasks/{id}/attachments/*``) plus the
per-surface caption PATCH from ADR 2026-05-21-attachment-caption.md:

    POST   /items/{id}/attachments/presign      (presign)
    POST   /items/{id}/attachments              (commit)
    GET    /items/{id}/attachments              (list)
    DELETE /items/{id}/attachments/{aid}        (delete)
    PATCH  /items/{id}/attachments/{aid}        (set/clear caption)

These tests pin only what the MCP OWNS: ref → resolved item path + correct body
(attachment ids are NOT item refs and pass through unresolved). Kind-neutrality
(Task/Chore/Habit) and Event rejection are backend behavior. **Suite-green here
means "MCP behaves correctly against the mocked contract", not "feature works
end-to-end" — re-confirm the route shapes against #215 before relying on them.**
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
ATT_ID = "att-abc-123"
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


# ── presign / commit / list ───────────────────────────────────────────────────


@respx.mock
async def test_presign_item_attachments_resolves_then_posts(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "chore"}))
    )
    presign = respx.post(f"{BASE}/items/{ITEM_UUID}/attachments/presign").mock(
        return_value=httpx.Response(200, json=_env([{"attachment_id": ATT_ID}]))
    )

    files = [{"filename": "a.png", "content_type": "image/png", "size_bytes": 10}]
    await _call(server, "presign_item_attachments", item_id="#123", files=files)

    assert by_seq.called and presign.called
    assert json.loads(presign.calls.last.request.content) == {"files": files}


@respx.mock
async def test_commit_item_attachments_resolves_then_posts(server):
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "habit"}))
    )
    commit = respx.post(f"{BASE}/items/{ITEM_UUID}/attachments").mock(
        return_value=httpx.Response(200, json=_env([{"id": ATT_ID}]))
    )

    await _call(
        server,
        "commit_item_attachments",
        item_id="u-1y0e2v-123",
        intents=[ATT_ID],
    )

    assert by_ref.called and commit.called
    assert json.loads(commit.calls.last.request.content) == {"intents": [ATT_ID]}


@respx.mock
async def test_list_item_attachments_resolves_then_gets(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "task"}))
    )
    listing = respx.get(f"{BASE}/items/{ITEM_UUID}/attachments").mock(
        return_value=httpx.Response(200, json=_env([{"id": ATT_ID}]))
    )

    result = await _call(server, "list_item_attachments", item_id="#123")
    out = json.loads(result)

    assert by_seq.called and listing.called
    assert out[0]["id"] == ATT_ID


# ── delete (att_id is not an item ref) ────────────────────────────────────────


@respx.mock
async def test_delete_item_attachment_resolves_item_only(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "chore"}))
    )
    delete = respx.delete(f"{BASE}/items/{ITEM_UUID}/attachments/{ATT_ID}").mock(
        return_value=httpx.Response(204)
    )

    result = await _call(
        server, "delete_item_attachment", item_id="#123", att_id=ATT_ID
    )
    out = json.loads(result)

    assert by_seq.called and delete.called
    # att_id is an attachment id, NOT an item ref — passed through verbatim.
    assert delete.calls.last.request.url.path == (
        f"/api/items/{ITEM_UUID}/attachments/{ATT_ID}"
    )
    assert out == {"ok": True}


# ── caption (PATCH at parent path) ────────────────────────────────────────────


@respx.mock
async def test_set_item_attachment_caption_patches_body(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "habit"}))
    )
    patch = respx.patch(f"{BASE}/items/{ITEM_UUID}/attachments/{ATT_ID}").mock(
        return_value=httpx.Response(200, json=_env({"id": ATT_ID, "caption": "a cat"}))
    )

    await _call(
        server,
        "set_item_attachment_caption",
        item_id="#123",
        att_id=ATT_ID,
        caption="a cat",
    )

    assert by_seq.called and patch.called
    assert json.loads(patch.calls.last.request.content) == {"caption": "a cat"}


@respx.mock
async def test_set_item_attachment_caption_clear_sends_null(server):
    """``caption=None`` clears — the body must carry an explicit JSON null
    (empty string is a backend 400 per the caption ADR, so null is the clear)."""
    respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "task"}))
    )
    patch = respx.patch(f"{BASE}/items/{ITEM_UUID}/attachments/{ATT_ID}").mock(
        return_value=httpx.Response(200, json=_env({"id": ATT_ID, "caption": None}))
    )

    await _call(
        server, "set_item_attachment_caption", item_id="#123", att_id=ATT_ID
    )

    assert patch.called
    assert json.loads(patch.calls.last.request.content) == {"caption": None}


# ── Event ref + date routes to the per-occurrence attachment path ──────────────


@respx.mock
async def test_presign_item_attachments_event_with_date_routes_to_occurrence(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    occ = respx.post(
        f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}/attachments/presign"
    ).mock(return_value=httpx.Response(200, json=_env([{"attachment_id": ATT_ID}])))
    item = respx.post(f"{BASE}/items/{ITEM_UUID}/attachments/presign")

    files = [{"filename": "a.png", "content_type": "image/png", "size_bytes": 10}]
    await _call(
        server, "presign_item_attachments", item_id="#123", files=files, date=DATE
    )

    assert by_seq.called and occ.called
    assert not item.called  # event+date does NOT hit the item-level path
    assert json.loads(occ.calls.last.request.content) == {"files": files}


@respx.mock
async def test_commit_item_attachments_event_with_date_routes_to_occurrence(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    occ = respx.post(f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}/attachments").mock(
        return_value=httpx.Response(200, json=_env([{"id": ATT_ID}]))
    )
    item = respx.post(f"{BASE}/items/{ITEM_UUID}/attachments")

    await _call(
        server,
        "commit_item_attachments",
        item_id="#123",
        intents=[ATT_ID],
        date=DATE,
    )

    assert by_seq.called and occ.called
    assert not item.called
    assert json.loads(occ.calls.last.request.content) == {"intents": [ATT_ID]}


@respx.mock
async def test_list_item_attachments_event_with_date_routes_to_occurrence(server):
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    occ = respx.get(f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}/attachments").mock(
        return_value=httpx.Response(200, json=_env([{"id": ATT_ID}]))
    )
    item = respx.get(f"{BASE}/items/{ITEM_UUID}/attachments")

    result = await _call(
        server, "list_item_attachments", item_id="#123", date=DATE
    )
    out = json.loads(result)

    assert by_seq.called and occ.called
    assert not item.called
    assert out[0]["id"] == ATT_ID


@respx.mock
async def test_delete_item_attachment_event_with_date_routes_to_occurrence(server):
    """Event+date routes the delete to the occurrence path; att_id rides through
    verbatim as the final path segment (it is NOT an item ref)."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    occ = respx.delete(
        f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}/attachments/{ATT_ID}"
    ).mock(return_value=httpx.Response(204))
    item = respx.delete(f"{BASE}/items/{ITEM_UUID}/attachments/{ATT_ID}")

    result = await _call(
        server,
        "delete_item_attachment",
        item_id="#123",
        att_id=ATT_ID,
        date=DATE,
    )
    out = json.loads(result)

    assert by_seq.called and occ.called
    assert not item.called
    assert occ.calls.last.request.url.path == (
        f"/api/events/{ITEM_UUID}/occurrences/{DATE}/attachments/{ATT_ID}"
    )
    assert out == {"ok": True}


@respx.mock
async def test_delete_item_attachment_no_date_hits_item_level(server):
    """An Event ref with NO date still deletes via the item-level path (backend
    400s there, but the MCP routing is correct)."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": ITEM_UUID, "kind": "event"}))
    )
    item = respx.delete(f"{BASE}/items/{ITEM_UUID}/attachments/{ATT_ID}").mock(
        return_value=httpx.Response(204)
    )
    occ = respx.delete(
        f"{BASE}/events/{ITEM_UUID}/occurrences/{DATE}/attachments/{ATT_ID}"
    )

    await _call(server, "delete_item_attachment", item_id="#123", att_id=ATT_ID)

    assert by_seq.called and item.called
    assert not occ.called  # no date -> no per-occurrence routing
