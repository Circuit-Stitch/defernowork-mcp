"""Unit tests for the shared Ref input form classifier + resolver (refs.py).

Covers the pure ``classify_ref`` classifier (one assertion group per
recognised Ref input form, plus the not-auto-routed/alias boundary) and the
async ``resolve_ref`` helper (per-form backend routing, via respx).

Vocabulary follows CONTEXT.md: Ref input form, Sequence shorthand, Canonical
ref, App URL, Transparent resolution.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from defernowork_mcp.client import DefernoClient, DefernoError
from defernowork_mcp.refs import (
    COMPACT_ITEM_FIELDS,
    RefForm,
    classify_ref,
    project,
    resolve_ref,
)

BASE = "http://test:3000/api"
UUID_STR = "11111111-2222-3333-4444-555555555555"


def _client() -> DefernoClient:
    return DefernoClient(base_url=BASE, token="test-token")


def _envelope(data):
    return {"version": "0.2", "data": data, "error": None}


# ── pure classifier: UUID ────────────────────────────────────────────────────


def test_classify_uuid():
    result = classify_ref(UUID_STR)
    assert result.form is RefForm.UUID
    assert result.uuid == UUID_STR


# ── pure classifier: Sequence shorthand ──────────────────────────────────────


def test_classify_sequence_shorthand_hash():
    result = classify_ref("#123")
    assert result.form is RefForm.SEQUENCE
    assert result.sequence == 123


def test_classify_sequence_shorthand_bare():
    result = classify_ref("123")
    assert result.form is RefForm.SEQUENCE
    assert result.sequence == 123


# ── pure classifier: Canonical ref ───────────────────────────────────────────


def test_classify_canonical_ref():
    result = classify_ref("acme-123")
    assert result.form is RefForm.CANONICAL
    assert result.canonical == "acme-123"
    assert result.org_slug == "acme"
    assert result.sequence == 123


def test_classify_canonical_ref_multi_hyphen_personal_slug():
    # Personal-org slugs look like ``u-1y0e2v``; the LAST hyphen separates
    # the slug from the sequence (matching the backend's rsplit_once).
    result = classify_ref("u-1y0e2v-123")
    assert result.form is RefForm.CANONICAL
    assert result.canonical == "u-1y0e2v-123"
    assert result.org_slug == "u-1y0e2v"
    assert result.sequence == 123


# ── pure classifier: not-auto-routed (alias / ambiguous boundary, issue #9) ──


def test_classify_uppercase_alias_is_not_auto_routed():
    # ``ABC-223`` is a GitHub/Jira-style Alias, not a Canonical ref: an org
    # slug must start lowercase, so this is explicitly NOT auto-routed (#9).
    result = classify_ref("ABC-223")
    assert result.form is RefForm.NOT_AUTO_ROUTED


def test_classify_owner_repo_alias_auto_routes_to_alias():
    # Issue #9: ``owner/repo#N`` is the UNAMBIGUOUS GitHub form — it contains a
    # ``/`` (so it can't be a Canonical ref or UUID) plus a ``#N`` suffix — and
    # now auto-routes to RefForm.ALIAS (was NOT_AUTO_ROUTED before #9).
    result = classify_ref("octo/repo#44")
    assert result.form is RefForm.ALIAS
    assert result.alias == "octo/repo#44"


def test_classify_garbage_is_not_auto_routed():
    assert classify_ref("not a ref").form is RefForm.NOT_AUTO_ROUTED
    assert classify_ref("acme-").form is RefForm.NOT_AUTO_ROUTED
    assert classify_ref("-123").form is RefForm.NOT_AUTO_ROUTED


def test_classify_ambiguous_forms_stay_not_auto_routed_after_alias():
    # Issue #9 ONLY auto-routes the unambiguous ``owner/repo#N`` shape. Every
    # other ambiguous form is unchanged — they have no ``/``-before-``#N``:
    #   - ``ABC-223`` collides with a Canonical ref (the explicit escape-hatch
    #     forces alias resolution for it; it is NOT auto-routed here).
    #   - bare ``#44`` is a Deferno Sequence shorthand (caught earlier), NOT a
    #     GitHub alias — this is the documented Deferno-`#` vs GitHub-`#`
    #     ambiguity; only ``owner/repo#N`` carries the ``/`` that disambiguates.
    assert classify_ref("ABC-223").form is RefForm.NOT_AUTO_ROUTED
    assert classify_ref("#44").form is RefForm.SEQUENCE
    assert classify_ref("acme-123").form is RefForm.CANONICAL


# ── pure classifier: App URL ─────────────────────────────────────────────────


def test_classify_app_url_with_sequence():
    result = classify_ref("https://app.defernowork.com/o/u-1y0e2v/items/123")
    assert result.form is RefForm.APP_URL
    assert result.org_slug == "u-1y0e2v"
    assert result.sequence == 123
    # A sequence-bearing App URL routes like a Canonical ref (by-ref),
    # because the URL may name a *shared* org, not the personal one.
    assert result.canonical == "u-1y0e2v-123"
    assert result.uuid is None


def test_classify_app_url_with_trailing_slash():
    result = classify_ref("https://app.defernowork.com/o/u-1y0e2v/items/123/")
    assert result.form is RefForm.APP_URL
    assert result.org_slug == "u-1y0e2v"
    assert result.sequence == 123
    assert result.canonical == "u-1y0e2v-123"


def test_classify_app_url_with_query_string():
    result = classify_ref(
        "https://app.defernowork.com/o/u-1y0e2v/items/123?foo=bar&x=1"
    )
    assert result.form is RefForm.APP_URL
    assert result.org_slug == "u-1y0e2v"
    assert result.sequence == 123
    assert result.canonical == "u-1y0e2v-123"


def test_classify_app_url_with_embedded_uuid():
    result = classify_ref(
        f"https://app.defernowork.com/o/u-1y0e2v/items/{UUID_STR}"
    )
    assert result.form is RefForm.APP_URL
    assert result.uuid == UUID_STR
    assert result.org_slug == "u-1y0e2v"
    assert result.sequence is None


def test_classify_malformed_app_url_is_not_auto_routed():
    # Right host, wrong path shape -> not auto-routed (don't guess).
    assert (
        classify_ref("https://app.defernowork.com/o/u-1y0e2v/tasks/123").form
        is RefForm.NOT_AUTO_ROUTED
    )


# ── async resolve_ref: per-form routing ──────────────────────────────────────


@respx.mock
async def test_resolve_ref_uuid_short_circuits_without_http():
    # A UUID needs no resolve round-trip — return it directly, zero HTTP.
    async with _client() as client:
        result = await resolve_ref(client, UUID_STR)
    assert result == UUID_STR
    assert not respx.calls.called


@respx.mock
async def test_resolve_ref_sequence_calls_by_seq():
    route = respx.get(f"{BASE}/items/by-seq/123").mock(
        return_value=httpx.Response(200, json=_envelope({"id": UUID_STR, "kind": "task"}))
    )
    async with _client() as client:
        result = await resolve_ref(client, "#123")
    assert route.called
    assert result == UUID_STR


@respx.mock
async def test_resolve_ref_canonical_calls_by_ref():
    route = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_envelope({"id": UUID_STR, "kind": "task"}))
    )
    async with _client() as client:
        result = await resolve_ref(client, "u-1y0e2v-123")
    assert route.called
    assert result == UUID_STR


@respx.mock
async def test_resolve_ref_github_alias_calls_by_alias():
    # Issue #9: the unambiguous GitHub form ``owner/repo#N`` resolves via
    # GET /items/by-alias/{alias}; the alias is URL-quoted with safe='' so
    # ``octo/repo#44`` -> ``octo%2Frepo%2344``.
    route = respx.get(f"{BASE}/items/by-alias/octo%2Frepo%2344").mock(
        return_value=httpx.Response(200, json=_envelope({"id": UUID_STR, "kind": "task"}))
    )
    async with _client() as client:
        result = await resolve_ref(client, "octo/repo#44")
    assert route.called
    assert result == UUID_STR


@respx.mock
async def test_resolve_ref_app_url_sequence_routes_by_ref():
    # App URL with a sequence resolves via by-ref (cross-org safe), NOT by-seq.
    route = respx.get(f"{BASE}/items/by-ref/u-1y0e2v-123").mock(
        return_value=httpx.Response(200, json=_envelope({"id": UUID_STR, "kind": "task"}))
    )
    async with _client() as client:
        result = await resolve_ref(
            client, "https://app.defernowork.com/o/u-1y0e2v/items/123"
        )
    assert route.called
    assert result == UUID_STR


@respx.mock
async def test_resolve_ref_app_url_uuid_short_circuits():
    async with _client() as client:
        result = await resolve_ref(
            client, f"https://app.defernowork.com/o/u-1y0e2v/items/{UUID_STR}"
        )
    assert result == UUID_STR
    assert not respx.calls.called


async def test_resolve_ref_not_auto_routed_raises():
    async with _client() as client:
        with pytest.raises(DefernoError) as exc_info:
            await resolve_ref(client, "ABC-223")
    assert exc_info.value.status_code == 400


@respx.mock
async def test_resolve_ref_not_found_propagates():
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
    async with _client() as client:
        with pytest.raises(DefernoError) as exc_info:
            await resolve_ref(client, "#999")
    assert exc_info.value.status_code == 404


# ── Compact projection helper ────────────────────────────────────────────────


def test_project_is_pick_if_present_whitelist():
    item = {
        "id": UUID_STR,
        "title": "Demo",
        "actions": [1, 2, 3],  # heavy field -> dropped
        "mood_start": [0.1, 0.2],  # heavy field -> dropped
    }
    out = project(item, ("id", "title", "status"))
    # Whitelisted-and-present kept; missing key ("status") simply absent;
    # non-whitelisted heavy keys dropped.
    assert out == {"id": UUID_STR, "title": "Demo"}


def test_compact_item_fields_keeps_both_discriminators_and_description():
    item = {
        "kind": "task",
        "type": "task",
        "id": UUID_STR,
        "ref": "u-1y0e2v-123",
        "sequence": 123,
        "org_slug": "u-1y0e2v",
        "title": "Demo",
        "status": "active",
        "labels": ["a"],
        "pinned": False,
        "parent_id": None,
        "complete_by": "2026-06-10T00:00:00Z",
        "date_created": "2026-06-01T00:00:00Z",
        "description": "the body",
        # heavy fields that must be omitted:
        "actions": [1, 2, 3],
        "comments": [{"body": "hi"}],
        "children": [{"id": "x"}],
        "mood_start": [0.1],
    }
    out = project(item, COMPACT_ITEM_FIELDS)
    # Both discriminator keys survive (backend emits BOTH on the wire).
    assert out["kind"] == "task"
    assert out["type"] == "task"
    # description stays IN the single-item compact view (owner decision).
    assert out["description"] == "the body"
    # heavy fields dropped
    assert "actions" not in out
    assert "comments" not in out
    assert "children" not in out
    assert "mood_start" not in out
