"""Shared Ref input form classifier and resolver (Transparent resolution).

This module is the reusable primitive behind *Transparent resolution* — the
MCP behaviour where every tool that takes an item identifier accepts any
**Ref input form** and resolves it to a UUID before acting (see CONTEXT.md and
docs/adr/0001-transparent-ref-resolution.md).

It exposes two things, deliberately decoupled from any single tool:

- :func:`classify_ref` — a *pure*, synchronous, side-effect-free classifier
  that inspects an agent-supplied string and returns a structured
  :class:`RefClassification`. It recognises every **unambiguous** Ref input
  form (UUID, Sequence shorthand, Canonical ref, App URL) and routes ambiguous
  / alias / GitHub forms to the explicit :attr:`RefForm.NOT_AUTO_ROUTED`
  outcome. Issue #9 extends this — *not* the callers.

- :func:`resolve_ref` — an *async* helper that classifies a ref, calls the
  matching Deferno read endpoint, and returns the item's **UUID**. This is the
  shared primitive issue #7 reuses to make every mutation tool ref-aware.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from urllib.parse import urlparse
from uuid import UUID

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .client import DefernoClient


class RefForm(Enum):
    """The recognised shapes of a **Ref input form**.

    ``UUID``, ``SEQUENCE``, ``CANONICAL`` and ``APP_URL`` are the unambiguous
    forms the MCP auto-routes. ``NOT_AUTO_ROUTED`` is the explicit sentinel for
    everything the classifier deliberately refuses to auto-route today —
    Alias / GitHub (``owner/repo#N``, ``ABC-223``) and any other ambiguous
    string. Issue #9 will add finer-grained alias outcomes here; callers should
    treat any non-auto-routed form as "needs the explicit alias path".
    """

    UUID = "uuid"
    SEQUENCE = "sequence"
    CANONICAL = "canonical"
    APP_URL = "app_url"
    NOT_AUTO_ROUTED = "not_auto_routed"


@dataclass(frozen=True)
class RefClassification:
    """The structured result of :func:`classify_ref`.

    ``form`` is always set. The extracted-part fields are populated only for
    the forms that carry them:

    - ``uuid`` — set for :attr:`RefForm.UUID`, and for an App URL whose final
      path segment is a UUID.
    - ``sequence`` — set for :attr:`RefForm.SEQUENCE`, and for an App URL whose
      final path segment is a sequence (paired with ``org_slug``).
    - ``canonical`` — the ``{org_slug}-{sequence}`` string for
      :attr:`RefForm.CANONICAL`, and synthesised for a sequence-bearing App URL.
    - ``org_slug`` — the org namespace, for canonical refs and app URLs.
    """

    form: RefForm
    uuid: str | None = None
    sequence: int | None = None
    canonical: str | None = None
    org_slug: str | None = None


# ── Compact projection (per ADR-0002) ───────────────────────────────────────
#
# Compact projection is a *whitelist* applied to a returned item: pick-if-
# present, so a missing key is simply absent. Heavy fields (action history,
# mood vectors, children, attachments, comments, subtask templates, recurrence
# /series internals) are never listed, so they are dropped.
#
# ``COMPACT_ITEM_CORE_FIELDS`` is the small shared core. It is deliberately
# exposed so issue #4's ``list_items`` can build its own (narrower) row set
# from it WITHOUT pulling in ``description`` — list rows exclude the body. The
# single-item ``get_item`` view extends the core with the heavier-but-still-one-
# string identity/audit fields plus ``description`` (owner decision: one string
# is fine for a single item; ``full=true`` returns everything).
#
# NOTE on the discriminator: the backend emits BOTH ``kind`` (the inner
# ItemView tag) AND ``type`` (the ItemEnvelope tag) on the wire for
# GET /items/{id}, by-seq, and by-ref. Both are whitelisted so dropping the
# discriminator can never happen, regardless of which key a future backend
# keeps.
COMPACT_ITEM_CORE_FIELDS: tuple[str, ...] = (
    "kind",
    "type",
    "ref",
    "title",
    "status",
    "complete_by",
    "parent_id",
    "labels",
)

COMPACT_ITEM_FIELDS: tuple[str, ...] = COMPACT_ITEM_CORE_FIELDS + (
    "id",
    "sequence",
    "org_slug",
    "pinned",
    "date_created",
    "description",
)


def project(item: dict, fields: "tuple[str, ...]") -> dict:
    """Apply a Compact projection whitelist to ``item`` (pick-if-present).

    Returns a new dict containing only the keys in ``fields`` that are present
    in ``item`` — missing keys are simply absent, extra keys are dropped. This
    is the shared mechanism behind every compact read; callers pass the field
    set they want (e.g. :data:`COMPACT_ITEM_FIELDS` for ``get_item``).
    """
    return {k: item[k] for k in fields if k in item}


async def resolve_ref(client: "DefernoClient", ref: str) -> str:
    """Resolve any **Ref input form** to the item's **UUID** (Transparent resolution).

    Classifies ``ref`` with :func:`classify_ref`, calls the matching Deferno
    read endpoint, and returns the resolved item's UUID. A UUID (or an App URL
    whose tail is a UUID) short-circuits with no HTTP round-trip — exactly what
    issue #7's mutation tools need to stay cheap.

    Routing:

    - ``UUID`` -> returned directly (no request).
    - ``SEQUENCE`` (``#123`` / bare ``123``) -> ``GET /items/by-seq/{seq}``
      (personal org only, by design).
    - ``CANONICAL`` (``slug-123``) -> ``GET /items/by-ref/{canonical}``
      (resolves the org slug globally — works across orgs).
    - ``APP_URL`` -> by id when the tail is a UUID, else by-ref using the
      embedded ``{slug}-{seq}`` (cross-org safe; never by-seq).
    - ``NOT_AUTO_ROUTED`` (Alias / GitHub / ambiguous) -> raises
      :class:`DefernoError` (400). Issue #9 owns the explicit alias path.

    Backend read errors (404 not-found, etc.) propagate as
    :class:`DefernoError`.
    """
    # Imported lazily to avoid a module-level import cycle (client imports
    # nothing from refs today, but keep resolve_ref self-contained).
    from .client import DefernoError

    c = classify_ref(ref)

    if c.form is RefForm.UUID:
        return c.uuid  # type: ignore[return-value]

    if c.form is RefForm.APP_URL and c.uuid is not None:
        return c.uuid

    if c.form is RefForm.SEQUENCE:
        item = await client.get_item_by_sequence(c.sequence)  # type: ignore[arg-type]
        return _uuid_of(item)

    if c.form in (RefForm.CANONICAL, RefForm.APP_URL):
        item = await client.get_item_by_ref(c.canonical)  # type: ignore[arg-type]
        return _uuid_of(item)

    raise DefernoError(
        400,
        f"identifier {ref!r} is not an auto-routable Ref input form "
        "(alias / ambiguous forms require the explicit alias lookup)",
    )


def _uuid_of(item: dict) -> str:
    """Extract the item UUID from a resolved ItemEnvelope payload."""
    return item["id"]


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _parse_sequence(value: str) -> int | None:
    """Parse a Sequence shorthand (``#123`` or bare ``123``) to an int.

    Mirrors the backend ``by-seq`` handler, which accepts both the ``#``-
    prefixed shorthand and a bare non-negative integer. Returns ``None`` for
    anything else (so the caller falls through to the next form).
    """
    rest = value[1:] if value.startswith("#") else value
    if rest.isdigit():
        return int(rest)
    return None


# Org-slug grammar, mirroring Deferno's backend ``org_slug::validate``
# (backend/src/org_slug.rs): 2-32 chars, starts with a lowercase ASCII
# letter, then lowercase ASCII letters / digits / hyphens with no
# consecutive and no trailing hyphen. This is the load-bearing rule that
# separates a *Canonical ref* (``u-1y0e2v-123`` — lowercase slug) from a
# GitHub/Jira-style *Alias* (``ABC-223`` — uppercase, not auto-routed; #9).
_SLUG_MIN_LEN = 2
_SLUG_MAX_LEN = 32


def _is_valid_org_slug(slug: str) -> bool:
    if not (_SLUG_MIN_LEN <= len(slug) <= _SLUG_MAX_LEN):
        return False
    if not (slug[0].isascii() and slug[0].islower() and slug[0].isalpha()):
        return False
    prev_hyphen = False
    for c in slug[1:]:
        if c == "-":
            if prev_hyphen:
                return False
            prev_hyphen = True
        elif c.isascii() and (c.islower() and c.isalpha() or c.isdigit()):
            prev_hyphen = False
        else:
            return False
    return not prev_hyphen


def _parse_canonical_ref(value: str) -> tuple[str, int] | None:
    """Split a Canonical ref ``{org_slug}-{sequence}`` on its LAST hyphen.

    Mirrors the backend ``parse_canonical_ref`` (rsplit on ``-``) and then
    additionally validates the left side against the org-slug grammar, so a
    lowercase ``u-1y0e2v-123`` resolves but an uppercase ``ABC-223`` Alias does
    not. Returns ``(org_slug, sequence)`` or ``None``.
    """
    slug, _, seq = value.rpartition("-")
    if not slug or not seq.isdigit():
        return None
    if not _is_valid_org_slug(slug):
        return None
    return slug, int(seq)


def _parse_app_url(value: str) -> RefClassification | None:
    """Parse an **App URL** (``/o/{org_slug}/items/{seq-or-id}``).

    Tolerates a trailing slash, query string, and fragment (urlparse strips
    query/fragment; trailing slash yields an empty final segment we drop). The
    final path segment is routed by shape:

    - a UUID -> ``RefForm.APP_URL`` carrying ``uuid`` (routes by id);
    - a sequence -> ``RefForm.APP_URL`` carrying ``org_slug`` + ``sequence`` +
      a synthesised ``canonical`` (``{slug}-{seq}``), so it routes by *ref*,
      not by-seq — the URL's org may be a shared org, and by-seq is
      personal-org-only.

    Returns ``None`` (fall through to the next form) when the string is not a
    recognised App URL path shape.
    """
    if "/o/" not in value:
        return None
    parsed = urlparse(value)
    segments = [seg for seg in parsed.path.split("/") if seg]
    # Expect exactly: ["o", <org_slug>, "items", <seq-or-id>]
    if len(segments) != 4 or segments[0] != "o" or segments[2] != "items":
        return None
    slug = segments[1]
    tail = segments[3]
    if not _is_valid_org_slug(slug):
        return None
    if _is_uuid(tail):
        return RefClassification(
            form=RefForm.APP_URL, uuid=tail, org_slug=slug
        )
    if tail.isdigit():
        n = int(tail)
        return RefClassification(
            form=RefForm.APP_URL,
            org_slug=slug,
            sequence=n,
            canonical=f"{slug}-{n}",
        )
    return None


def classify_ref(value: str) -> RefClassification:
    """Classify an agent-supplied identifier string into a Ref input form.

    Pure and synchronous: no I/O, no globals. Order matters — UUID is checked
    before the canonical-ref shape because a UUID also matches
    ``{slug}-{digits}`` under a naive split.
    """
    s = value.strip()

    if _is_uuid(s):
        return RefClassification(form=RefForm.UUID, uuid=s)

    app_url = _parse_app_url(s)
    if app_url is not None:
        return app_url

    seq = _parse_sequence(s)
    if seq is not None:
        return RefClassification(form=RefForm.SEQUENCE, sequence=seq)

    canonical = _parse_canonical_ref(s)
    if canonical is not None:
        slug, n = canonical
        return RefClassification(
            form=RefForm.CANONICAL,
            canonical=s,
            org_slug=slug,
            sequence=n,
        )

    return RefClassification(form=RefForm.NOT_AUTO_ROUTED)
