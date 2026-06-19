"""Unit tests for refs.resolve_ref_with_kind (kind-neutral dispatch primitive).

It returns (uuid, kind) for any Ref input form: a non-UUID ref learns the kind
from its resolve round-trip; a raw UUID pays one GET /items/{id} (it has no kind
locally); casing is normalised to lowercase; a NOT_AUTO_ROUTED ref raises 400.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from defernowork_mcp.client import DefernoClient, DefernoError
from defernowork_mcp.refs import resolve_ref_with_kind

BASE = "http://test:3000/api"
UUID = "11111111-2222-3333-4444-555555555555"


def _env(data):
    return {"version": "0.2", "data": data, "error": None}


@respx.mock
@pytest.mark.asyncio
async def test_uuid_does_one_get_to_learn_kind():
    """A raw UUID has no kind locally -> one GET /items/{id} to discover it."""
    by_seq = respx.get(f"{BASE}/items/by-seq/123")
    get = respx.get(f"{BASE}/items/{UUID}").mock(
        return_value=httpx.Response(200, json=_env({"id": UUID, "kind": "Chore"}))
    )
    async with DefernoClient(base_url=BASE, token="t") as client:
        uuid, kind = await resolve_ref_with_kind(client, UUID)
    assert get.called and not by_seq.called
    assert uuid == UUID
    assert kind == "chore"  # capitalised wire value lowercased


@respx.mock
@pytest.mark.asyncio
async def test_sequence_learns_kind_from_resolve():
    by_seq = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_env({"id": UUID, "kind": "habit"}))
    )
    items = respx.get(f"{BASE}/items/{UUID}")
    async with DefernoClient(base_url=BASE, token="t") as client:
        uuid, kind = await resolve_ref_with_kind(client, "#123")
    assert by_seq.called and not items.called  # no extra GET — kind came free
    assert (uuid, kind) == (UUID, "habit")


@respx.mock
@pytest.mark.asyncio
async def test_canonical_learns_kind_from_by_ref():
    by_ref = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_env({"id": UUID, "kind": "event"}))
    )
    async with DefernoClient(base_url=BASE, token="t") as client:
        uuid, kind = await resolve_ref_with_kind(client, "u-1y0e2v-123")
    assert by_ref.called
    assert (uuid, kind) == (UUID, "event")


@respx.mock
@pytest.mark.asyncio
async def test_not_auto_routed_raises_400():
    async with DefernoClient(base_url=BASE, token="t") as client:
        with pytest.raises(DefernoError) as exc:
            await resolve_ref_with_kind(client, "ABC-223")
    assert exc.value.status_code == 400
