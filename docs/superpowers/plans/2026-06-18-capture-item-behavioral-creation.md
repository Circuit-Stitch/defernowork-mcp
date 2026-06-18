# capture_item — Behavioral, Caller-Categorized Item Creation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Collapse the four per-kind create tools into one behavioral `capture_item` front door (plus the retained low-level `create_task` escape), per ADR-0003.

**Architecture:** A pure, side-effect-free `derive_create_payload()` reads three behavioral discriminators (`attend`, `repeats`, `obligation`) and deterministically returns `(kind, wire-payload)` — the ADR-0003 kind-derivation tree, the canonical cross-repo contract, tested against golden vectors. A thin `capture_item` MCP tool calls it, then dispatches to the existing `client.create_{task,chore,habit,event}` methods (whose wire bodies are already proven against the backend). `complete_by` is supplied by the caller as a full ISO-8601 datetime — exactly as the existing `create_task`/`create_event` tools already require — so the MCP does **no timezone work**. The three per-kind create MCP tools are removed; their `client.*` methods, `update_*`/`delete_*`/occurrence tools, and backend endpoints all stay.

**Tech Stack:** Python 3.10+, FastMCP, pydantic, pytest + pytest-asyncio + respx. (No new dependency.)

---

## Background facts (verified this session — do not re-derive)

**Backend create wire contract** (`Deferno/backend/src/payloads.rs`, confirmed against `deferno-kmp` `CreatePayloadDto.kt` + `CreatePayloadSerializationTest.kt`). All keys snake_case; null/absent optionals omitted:

| Endpoint | Required | Optional "when" fields | Other optional |
|----------|----------|------------------------|----------------|
| `POST /tasks`  | `title` | `complete_by` (ISO-8601 datetime), `deadline_time_of_day` (`"HH:MM"`) | `description`, `labels`, `parent_id`, `productive`, `desire` |
| `POST /chores` | `title`, `recurrence` | `complete_by`, `deadline_time_of_day` | `description`, `labels`, `parent_id`, `cadence_mode`, … |
| `POST /habits` | `title`, `recurrence` | `complete_by`, `deadline_time_of_day` | `description`, `labels`, `parent_id`, … |
| `POST /events` | `title`, `complete_by` | `start_time_of_day`, `end_time`, `end_time_of_day` | `description`, `labels`, `parent_id`, `recurrence` |

- A capture `time_of_day` maps to `start_time_of_day` for an **Event**, `deadline_time_of_day` for **Task/Chore/Habit**.
- `Tasks` are non-recurring (backend 422s any `recurrence` on `/tasks`); the Task branch never emits `recurrence`.

**`complete_by` is caller-supplied (design decision this session).** It is a full RFC3339 datetime that the *caller* (the agent) builds from the user's local context — identical to how `create_task`/`create_event` already work today, so `capture_item`'s payloads are byte-for-byte consistent with the proven existing surface. The MCP performs **no** timezone resolution and adds **no** dependency. (Background, not MCP logic: the backend reads only the *local calendar date* of `complete_by` in the user's stored tz and re-attaches `time_of_day` — `time.rs normalize_when_instant`; the agent is responsible for producing an instant on the intended local day, exactly as for `create_task`.)

**The derivation tree (ADR-0003):**
```
attend            → Event   (wins over recurrence; recurrence rides along)
else !repeats     → Task
else obligation == "need" → Chore
     obligation == "want" → Habit
```

**User decisions this session:** Q3 = behavioral `obligation: "need" | "want"` (not KMP's `ifMissed`/`carries_forward`/`lapses`). When-field = caller-provided `complete_by` (full datetime, like `create_task`) + optional `time_of_day`; the MCP does no tz math (reverses the earlier bare-`date` idea after the tz cost surfaced).

**Canonical-contract boundary:** the cross-repo canonical artifact is the **kind-derivation tree + field routing** (`derive_create_payload`). `deferno-kmp`'s `CaptureInput` still carries the rejected `occursAtSetTime` discriminator — reconciling KMP is handoff step 3 (separate repo, NOT in this plan). Our vectors are canonical, pending that amend. (KMP, a device client, accepts a bare `date` because it has the device tz; the MCP, a server with no ambient tz, takes a caller-built `complete_by` instead. Both implement the same tree — the divergence is in the tz-bearing operand only, which ADR-0003 already treats as an orthogonal operand, not a discriminator.)

**No MCP tool-count assertion exists** (grep of `tests/` found none); removing three tools needs no count update. `tests/inventory.py` cross-checks *endpoints*, which are unchanged.

---

## Pre-flight (uncommitted prior-session work)

`git status` shows `M README.md` and untracked `docs/adr/0003-...md` from the session that wrote ADR-0003. These are the foundation this plan builds on. **Do not discard them.** They get committed alongside the doc task (Task 6) that updates them, or commit them first as a standalone "docs: land ADR-0003 + README capture section" commit if you prefer a clean base. Confirm with the user before the first commit if unsure.

---

## File Structure

- **Create** `src/defernowork_mcp/capture.py` — the pure derivation: `derive_create_payload()`, `CaptureError`. No I/O, no FastMCP, no client, no tz. The single TDD target.
- **Create** `src/defernowork_mcp/tools/capture.py` — `register()` defining the `capture_item` `@mcp.tool()`; calls `derive_create_payload`, dispatches to `client.create_*`.
- **Modify** `src/defernowork_mcp/tools/__init__.py` — export `register_capture`.
- **Modify** `src/defernowork_mcp/server.py` — register `capture_item`; update the `instructions` blurb.
- **Modify** `src/defernowork_mcp/tools/chores.py`, `habits.py`, `events.py` — delete only the `create_*` tool functions.
- **Create** `tests/spec/capture/vectors.json` — golden input→(kind,payload) vectors for the derivation tree.
- **Create** `tests/test_capture_derivation.py` — parametrized over the golden vectors (happy + raises).
- **Create** `tests/test_capture_item_tool.py` — respx integration for `capture_item`.
- **Modify** `tests/spec/v0.1/chores/create.json`, `habits/create.json`, `events/create.json` — drop the `mcp_tool` binding.
- **Modify** `tests/test_constraint_docs.py` — retarget `RECURRENCE_TOOLS` / `EVENT_TOOLS`.
- **Modify** `tests/test_ref_resolution_secondary.py` — delete the three create_{chore,habit,event} parent_id tests.
- **Modify** `README.md`, `docs/adr/0003-...md` — align with the implemented signature.

---

## ⚠️ Test-behavior changes this plan makes (surface to the user — global CLAUDE.md rule)

These are intentional and flow from ADR-0003, but each must be **named, not buried**:

1. **`tests/test_ref_resolution_secondary.py`: three tests deleted** (`create_chore`/`create_habit`/`create_event` `parent_id` ref-resolution). **Coverage gap opened:** creating a Chore/Habit/Event *under a parent via a ref form* is no longer possible — `capture_item` carries no `parent_id`; only `create_task` does (ADR-0003 keeps `parent_id` a Task-only escape). `create_task`'s two parent_id tests stay.
2. **`tests/test_constraint_docs.py`: `EVENT_TOOLS` loses `create_event`** → only `update_event` remains. **Coverage reduction:** the event-`end_time` constraint is no longer asserted on any *create* path, because no create tool carries `end_time` anymore (capture omits it; Events get `end_time` via `update_event`).
3. **`tests/test_constraint_docs.py`: `RECURRENCE_TOOLS` swaps the three `create_*` for `capture_item`.** Net recurrence-end-constraint coverage on the create path is **preserved** (capture is the create path) — but the asserted tool changes.
4. **`tests/test_tools_contract.py`: three parametrized cases disappear** (`chores.create`, `habits.create`, `events.create`) when their fixtures drop `mcp_tool`. The create path's MCP-tool-layer coverage **moves** to `tests/test_capture_item_tool.py`. Client-layer coverage (`client_method`) is untouched.

No assertion is *weakened in place* and no production behavior a test pinned is changed silently — the removed `create_*` tools cease to exist by design.

---

### Task 1: Pure derivation — `derive_create_payload`

**Files:**
- Create: `src/defernowork_mcp/capture.py`
- Create: `tests/spec/capture/vectors.json`
- Test: `tests/test_capture_derivation.py`

- [ ] **Step 1: Write the golden vectors fixture**

Create `tests/spec/capture/vectors.json`:

```json
{
  "_doc": "Golden behavioral-input -> (kind, payload) vectors for the ADR-0003 kind-derivation tree (the cross-repo canonical contract). complete_by is a caller-supplied full datetime, passed through verbatim. CANONICAL here; deferno-kmp's deriveCreatePayload must adopt the attend/need-want discriminator to match -- PENDING that KMP amend.",
  "ok": [
    {
      "name": "attend -> event",
      "input": {"title": "Dentist", "attend": true, "repeats": false, "complete_by": "2026-07-01T16:00:00Z"},
      "kind": "event",
      "payload": {"title": "Dentist", "complete_by": "2026-07-01T16:00:00Z"}
    },
    {
      "name": "attend + repeats -> event (recurrence carried, obligation ignored)",
      "input": {"title": "Stand-up", "attend": true, "repeats": true, "complete_by": "2026-07-01T16:00:00Z", "recurrence": {"type": "weekly", "days": ["Mon"]}},
      "kind": "event",
      "payload": {"title": "Stand-up", "complete_by": "2026-07-01T16:00:00Z", "recurrence": {"type": "weekly", "days": ["Mon"]}}
    },
    {
      "name": "event time_of_day -> start_time_of_day",
      "input": {"title": "Call", "attend": true, "repeats": false, "complete_by": "2026-07-01T16:00:00Z", "time_of_day": "09:30"},
      "kind": "event",
      "payload": {"title": "Call", "complete_by": "2026-07-01T16:00:00Z", "start_time_of_day": "09:30"}
    },
    {
      "name": "no attend, no repeat -> task",
      "input": {"title": "Buy milk", "attend": false, "repeats": false},
      "kind": "task",
      "payload": {"title": "Buy milk"}
    },
    {
      "name": "task complete_by+time_of_day -> deadline_time_of_day",
      "input": {"title": "File taxes", "attend": false, "repeats": false, "complete_by": "2026-04-15T16:00:00Z", "time_of_day": "17:00", "description": "before EOD"},
      "kind": "task",
      "payload": {"title": "File taxes", "description": "before EOD", "complete_by": "2026-04-15T16:00:00Z", "deadline_time_of_day": "17:00"}
    },
    {
      "name": "repeats + need -> chore",
      "input": {"title": "Take out trash", "attend": false, "repeats": true, "obligation": "need", "recurrence": {"type": "weekly", "days": ["Tue"]}, "complete_by": "2026-06-23T16:00:00Z"},
      "kind": "chore",
      "payload": {"title": "Take out trash", "recurrence": {"type": "weekly", "days": ["Tue"]}, "complete_by": "2026-06-23T16:00:00Z"}
    },
    {
      "name": "repeats + want -> habit",
      "input": {"title": "Stretch", "attend": false, "repeats": true, "obligation": "want", "recurrence": {"type": "daily"}},
      "kind": "habit",
      "payload": {"title": "Stretch", "recurrence": {"type": "daily"}}
    }
  ],
  "raises": [
    {"name": "blank title", "input": {"title": "  ", "attend": false, "repeats": false}, "message_contains": "non-blank title"},
    {"name": "event without complete_by", "input": {"title": "Meeting", "attend": true, "repeats": false}, "message_contains": "complete_by"},
    {"name": "repeating without recurrence", "input": {"title": "Stretch", "attend": false, "repeats": true, "obligation": "want"}, "message_contains": "recurrence"},
    {"name": "repeating without obligation", "input": {"title": "Stretch", "attend": false, "repeats": true, "recurrence": {"type": "daily"}}, "message_contains": "obligation"}
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_capture_derivation.py`:

```python
"""Golden-vector tests for the ADR-0003 behavioral-capture derivation.

The vectors in tests/spec/capture/vectors.json are the CANONICAL spec the
deferno-kmp CaptureInput.deriveCreatePayload must match (pending the KMP amend).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from defernowork_mcp.capture import CaptureError, derive_create_payload

_VECTORS = json.loads(
    (Path(__file__).resolve().parent / "spec" / "capture" / "vectors.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("vec", _VECTORS["ok"], ids=[v["name"] for v in _VECTORS["ok"]])
def test_derive_ok(vec):
    kind, payload = derive_create_payload(**vec["input"])
    assert kind == vec["kind"]
    assert payload == vec["payload"]


@pytest.mark.parametrize(
    "vec", _VECTORS["raises"], ids=[v["name"] for v in _VECTORS["raises"]]
)
def test_derive_raises(vec):
    with pytest.raises(CaptureError) as excinfo:
        derive_create_payload(**vec["input"])
    assert vec["message_contains"] in str(excinfo.value)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_capture_derivation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'defernowork_mcp.capture'`.

- [ ] **Step 4: Write the implementation**

Create `src/defernowork_mcp/capture.py`:

```python
"""Caller-categorized item creation: the behavioral-capture derivation (ADR-0003).

One jargon-free behavioral schema -> a deterministic ``(kind, create-payload)``.
No inference, no model call: the kind is read straight off three behavioral
discriminators (the ADR-0003 kind-derivation tree). ``complete_by`` is supplied by
the caller as a full datetime (like ``create_task``) and passed through verbatim --
no timezone work here. Defined and tested once; kept in lockstep with deferno-kmp's
``CaptureInput.deriveCreatePayload`` via the golden vectors in tests/spec/capture/
-- canonical here, pending the KMP amend.
"""

from __future__ import annotations

from typing import Any, Literal


class CaptureError(ValueError):
    """A capture input that cannot be mapped to a kind + create payload.

    Raised at the capture trust boundary (an external caller fills the schema):
    a blank title, an Event with no ``complete_by``, or a repeating capture
    missing its recurrence cadence or its need/want answer. Never a
    silently-wrong kind.
    """


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


def derive_create_payload(
    *,
    title: str,
    attend: bool,
    repeats: bool,
    obligation: Literal["need", "want"] | None = None,
    complete_by: str | None = None,
    time_of_day: str | None = None,
    recurrence: dict[str, Any] | None = None,
    description: str | None = None,
) -> tuple[str, dict[str, Any]]:
    """Apply the ADR-0003 kind-derivation tree -> ``(kind, create payload)``.

        attend                    -> Event   (wins over recurrence)
        else not repeats          -> Task
        else obligation == "need" -> Chore
             obligation == "want" -> Habit

    ``complete_by`` is the caller-supplied wire datetime, passed through.
    ``kind`` is one of ``"task"`` / ``"chore"`` / ``"habit"`` / ``"event"``;
    ``payload`` is the kind-specific POST body with None-valued keys dropped.
    Raises :class:`CaptureError` on a malformed input.
    """
    if not title or not title.strip():
        raise CaptureError("a capture requires a non-blank title")

    # Q1 -- attend -> Event (a thing you attend is an Event whether or not it
    # repeats; a recurrence rides along and the need/want answer is not asked).
    if attend:
        if complete_by is None:
            raise CaptureError("an Event capture (attend=true) requires complete_by")
        return "event", _drop_none(
            {
                "title": title,
                "complete_by": complete_by,
                "start_time_of_day": time_of_day,
                "recurrence": recurrence,
                "description": description,
            }
        )

    # Q2 -- does not repeat -> one-off Task (a one-off has no cadence for a Habit
    # to land on; Tasks are non-recurring, so no recurrence is emitted).
    if not repeats:
        return "task", _drop_none(
            {
                "title": title,
                "description": description,
                "complete_by": complete_by,
                "deadline_time_of_day": time_of_day,
            }
        )

    # Q3 -- repeats: need (carries forward) -> Chore, want (lapses) -> Habit.
    if recurrence is None:
        raise CaptureError("a repeating capture requires a recurrence cadence")
    if obligation not in ("need", "want"):
        raise CaptureError(
            "a repeating capture requires obligation='need' (-> Chore) or "
            "'want' (-> Habit)"
        )
    kind = "chore" if obligation == "need" else "habit"
    return kind, _drop_none(
        {
            "title": title,
            "recurrence": recurrence,
            "description": description,
            "complete_by": complete_by,
            "deadline_time_of_day": time_of_day,
        }
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_capture_derivation.py -v`
Expected: PASS — all `ok` and `raises` vectors green.

- [ ] **Step 6: Commit**

```bash
git add src/defernowork_mcp/capture.py tests/spec/capture/vectors.json tests/test_capture_derivation.py
git commit -m "feat(capture): pure kind-derivation for behavioral capture (ADR-0003)"
```

---

### Task 2: The `capture_item` tool + wiring

**Files:**
- Create: `src/defernowork_mcp/tools/capture.py`
- Modify: `src/defernowork_mcp/tools/__init__.py`
- Modify: `src/defernowork_mcp/server.py` (`from .tools import (...)`, the register block ~line 297; the `instructions` ~262-286 in Task 6)
- Test: `tests/test_capture_item_tool.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_capture_item_tool.py`:

```python
"""respx integration for the capture_item tool: derive -> dispatch -> POST."""

from __future__ import annotations

import inspect
import json

import httpx
import pytest
import respx

from defernowork_mcp import server as srv
from defernowork_mcp.client import DefernoClient

BASE = "http://test:3000/api"
NEW_ID = "00000000-0000-0000-0000-000000000001"


def _env(data):
    return {"version": "0.2", "data": data, "error": None}


def _created(kind):
    return _env({"id": NEW_ID, "kind": kind, "title": "x", "status": "open"})


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


@respx.mock
@pytest.mark.asyncio
async def test_task_minimal_posts_tasks(server):
    route = respx.post(f"{BASE}/tasks").mock(
        return_value=httpx.Response(201, json=_created("task"))
    )
    out = await _call(server, "capture_item", title="Buy milk", attend=False, repeats=False)
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body == {"title": "Buy milk"}  # nulls omitted, no recurrence key
    assert json.loads(out)["id"] == NEW_ID


@respx.mock
@pytest.mark.asyncio
async def test_event_passes_complete_by_through_and_maps_start_tod(server):
    route = respx.post(f"{BASE}/events").mock(
        return_value=httpx.Response(201, json=_created("event"))
    )
    await _call(
        server, "capture_item", title="Call", attend=True, repeats=False,
        complete_by="2026-07-01T16:00:00Z", time_of_day="09:30",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["complete_by"] == "2026-07-01T16:00:00Z"  # passed through verbatim
    assert body["start_time_of_day"] == "09:30"
    assert "deadline_time_of_day" not in body


@respx.mock
@pytest.mark.asyncio
async def test_need_posts_chores(server):
    route = respx.post(f"{BASE}/chores").mock(
        return_value=httpx.Response(201, json=_created("chore"))
    )
    await _call(
        server, "capture_item", title="Trash", attend=False, repeats=True,
        obligation="need", recurrence={"type": "weekly", "days": ["Tue"]},
        complete_by="2026-06-23T16:00:00Z", time_of_day="20:00",
    )
    body = json.loads(route.calls.last.request.content)
    assert body["recurrence"] == {"type": "weekly", "days": ["Tue"]}
    assert body["complete_by"] == "2026-06-23T16:00:00Z"
    assert body["deadline_time_of_day"] == "20:00"


@respx.mock
@pytest.mark.asyncio
async def test_want_posts_habits(server):
    route = respx.post(f"{BASE}/habits").mock(
        return_value=httpx.Response(201, json=_created("habit"))
    )
    await _call(
        server, "capture_item", title="Stretch", attend=False, repeats=True,
        obligation="want", recurrence={"type": "daily"},
    )
    assert route.called
    body = json.loads(route.calls.last.request.content)
    assert body["recurrence"] == {"type": "daily"}


@respx.mock
@pytest.mark.asyncio
async def test_validation_error_short_circuits_before_post(server):
    route = respx.post(f"{BASE}/events").mock(
        return_value=httpx.Response(201, json=_created("event"))
    )
    out = await _call(server, "capture_item", title="Meeting", attend=True, repeats=False)
    assert not route.called  # no complete_by -> derive raises before any HTTP call
    assert "complete_by" in out


def test_capture_item_has_no_parent_id_param(server):
    sig = inspect.signature(_tool(server, "capture_item").fn)
    assert "parent_id" not in sig.parameters  # ADR-0003: parent_id is create_task-only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_capture_item_tool.py -v`
Expected: FAIL — `LookupError: tool 'capture_item' not registered`.

- [ ] **Step 3: Create the tool module**

Create `src/defernowork_mcp/tools/capture.py`:

```python
"""The behavioral-capture tool -- the single create front door (ADR-0003)."""

from __future__ import annotations

import json
from typing import Annotated, Any, Awaitable, Callable, Literal

from mcp.server.fastmcp import Context, FastMCP
from pydantic import Field

from ..capture import CaptureError, derive_create_payload
from ..client import DefernoClient, DefernoError
from ..constraints import RECURRENCE_END_DESC


def register(
    mcp: FastMCP,
    get_client: Callable[..., Awaitable[DefernoClient]],
    format_error: Callable[[DefernoError], str],
) -> None:
    @mcp.tool()
    async def capture_item(
        title: str,
        attend: bool,
        repeats: bool,
        obligation: Literal["need", "want"] | None = None,
        complete_by: str | None = None,
        time_of_day: str | None = None,
        recurrence: Annotated[
            dict[str, Any] | None, Field(description=RECURRENCE_END_DESC)
        ] = None,
        description: str | None = None,
        ctx: Context = None,
    ) -> str:
        """Capture a new item by how it *behaves*; the server derives the kind.

        Answer three behavioral questions from world knowledge -- never naming a
        Deferno kind -- and the server deterministically picks Task / Chore /
        Habit / Event and builds the create payload:

        - ``attend`` -- do you *attend* it at a time (a meeting, appointment,
          class)? -> **Event**. Attendance wins over recurrence: a weekly
          stand-up is still an Event.
        - ``repeats`` -- does it recur on a schedule? A one-off -> **Task**.
        - ``obligation`` -- for a recurring, non-attended thing: does it **need**
          to happen (an obligation that carries forward if missed) -> **Chore**,
          or do you just **want** to at that cadence (an aspiration that lapses)
          -> **Habit**? Required when ``repeats`` and not ``attend``.

        ``complete_by`` is a full ISO-8601 datetime (an Event's day, else the
        deadline / series-start day) -- required for an Event. As with
        ``create_task``, supply it in the user's intended local day; the backend
        keys off its calendar date in the user's saved timezone. ``time_of_day``
        is ``HH:MM`` wall-clock (the Event start, else the deadline time).
        ``recurrence`` is the cadence (required for a recurring Chore/Habit); if
        its ``end`` is ``{type: on_date, date}``, that date must be on or after
        the series start (``complete_by``'s local calendar date) -- same-day is
        allowed.

        This is the single create front door. For a subtask under a parent, a
        ``desire`` score, or sequence chains, use ``create_task``. Advanced
        recurring-kind fields (``end_time``, ``cadence_mode``,
        ``subtask_template``, a recurrence ``end``) are a follow-up ``update_*``
        after capture.
        """
        try:
            kind, payload = derive_create_payload(
                title=title,
                attend=attend,
                repeats=repeats,
                obligation=obligation,
                complete_by=complete_by,
                time_of_day=time_of_day,
                recurrence=recurrence,
                description=description,
            )
        except CaptureError as exc:
            return f"capture_item: {exc}"

        async with (await get_client(ctx=ctx)) as client:
            creators = {
                "task": client.create_task,
                "chore": client.create_chore,
                "habit": client.create_habit,
                "event": client.create_event,
            }
            try:
                result = await creators[kind](payload)
            except DefernoError as exc:
                return format_error(exc)
        return json.dumps(result)
```

- [ ] **Step 4: Export and register it**

In `src/defernowork_mcp/tools/__init__.py`, add the import (after `register_auth`) and the `__all__` entry:

```python
from .capture import register as register_capture
```
```python
    "register_capture",
```

In `src/defernowork_mcp/server.py`, add `register_capture` to the `from .tools import (...)` block, and register it right after `register_tasks`:

```python
    register_tasks(mcp, _get_client_async, _format_error, _compact, _UNSET)
    register_capture(mcp, _get_client_async, _format_error)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_capture_item_tool.py -v`
Expected: PASS — all five respx cases + the no-parent_id signature check green.

- [ ] **Step 6: Commit**

```bash
git add src/defernowork_mcp/tools/capture.py src/defernowork_mcp/tools/__init__.py src/defernowork_mcp/server.py tests/test_capture_item_tool.py
git commit -m "feat(capture): add capture_item tool dispatching to create_* (ADR-0003)"
```

---

### Task 3: Remove the three per-kind create tools

**Files:**
- Modify: `src/defernowork_mcp/tools/chores.py:23-75` (delete `create_chore`)
- Modify: `src/defernowork_mcp/tools/habits.py:23-68` (delete `create_habit`)
- Modify: `src/defernowork_mcp/tools/events.py:31-76` (delete `create_event`)

> Delete **only** the `@mcp.tool() async def create_chore/create_habit/create_event` functions. Keep every `update_*`, `delete_*`, occurrence tool, and the module-level imports / `EVENT_END_TIME_DESC` they share (`update_event` still uses `EVENT_END_TIME_DESC`; `update_chore`/`update_habit` still use `RECURRENCE_END_DESC` + `Annotated`/`Field`). After deletion, confirm no import becomes unused.

- [ ] **Step 1: Add a guard test that the tools are gone**

Append to `tests/test_capture_item_tool.py`:

```python
@pytest.mark.parametrize("removed", ["create_chore", "create_habit", "create_event"])
def test_per_kind_create_tools_removed(server, removed):
    with pytest.raises(LookupError):
        _tool(server, removed)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_capture_item_tool.py -k removed -v`
Expected: FAIL — the tools are still registered, so `_tool` does not raise.

- [ ] **Step 3: Delete the three `create_*` tool functions**

Remove the `create_chore` function from `tools/chores.py`, `create_habit` from `tools/habits.py`, `create_event` from `tools/events.py` (the `@mcp.tool()`-decorated `async def` blocks only).

- [ ] **Step 4: Run it + verify clean imports**

Run: `python -m pytest tests/test_capture_item_tool.py -k removed -v`
Expected: PASS — `_tool` raises `LookupError` for all three.

Then: `python -c "import defernowork_mcp.tools.chores, defernowork_mcp.tools.habits, defernowork_mcp.tools.events"` — must import with no error.

- [ ] **Step 5: Commit**

```bash
git add src/defernowork_mcp/tools/chores.py src/defernowork_mcp/tools/habits.py src/defernowork_mcp/tools/events.py tests/test_capture_item_tool.py
git commit -m "feat(capture): remove per-kind create_chore/habit/event tools (ADR-0003)"
```

---

### Task 4: Repair the constraint-doc tests (SURFACE changes 2 & 3)

**Files:**
- Modify: `tests/test_constraint_docs.py:24-33`

- [ ] **Step 1: Retarget the tool lists**

Replace the `RECURRENCE_TOOLS` and `EVENT_TOOLS` definitions:

```python
# All create/update tools that take a bounded ``recurrence``.
# create_chore/habit/event were folded into capture_item (ADR-0003).
RECURRENCE_TOOLS = [
    "update_event",
    "update_chore",
    "update_habit",
    "capture_item",
]
# Tools that take an event ``end_time``. create_event was removed (ADR-0003);
# capture_item carries no end_time (set via update_event), so only update_event
# documents the end_time >= complete_by constraint on the surface now.
EVENT_TOOLS = ["update_event"]
```

- [ ] **Step 2: Run the constraint-doc tests**

Run: `python -m pytest tests/test_constraint_docs.py -v`
Expected: PASS — `capture_item`'s docstring contains "on or after the series start" and its `recurrence` param schema carries `RECURRENCE_END_DESC`; `recurrence` stays optional; `update_event` still documents `end_time`.

> If `test_recurrence_param_stays_optional[capture_item]` fails, `recurrence` was made required — it must keep its `= None` default. If the docstring test fails, the Task-2 docstring lost the "on or after the series start" phrase; restore it.

- [ ] **Step 3: Commit**

```bash
git add tests/test_constraint_docs.py
git commit -m "test(capture): retarget constraint-doc tools to capture_item (ADR-0003)"
```

---

### Task 5: Repair fixture + ref-resolution regressions (SURFACE changes 1 & 4)

**Files:**
- Modify: `tests/spec/v0.1/chores/create.json`, `habits/create.json`, `events/create.json`
- Modify: `tests/test_ref_resolution_secondary.py`

- [ ] **Step 1: Drop the `mcp_tool` binding from the three create fixtures**

In each of `tests/spec/v0.1/chores/create.json`, `habits/create.json`, `events/create.json`, delete the two trailing keys so the fixture keeps `client_method` (client-layer coverage) but no longer drives `test_tools_contract.py`:

Remove these lines from each file (matching the per-file tool name):
```json
  "mcp_tool": "create_chore",
  "mcp_tool_args_from_example": ["title"]
```
Make `"client_method": "create_chore"` (resp. `create_habit`/`create_event`) the last key — drop its trailing comma so the JSON stays valid.

- [ ] **Step 2: Delete the three create_{chore,habit,event} parent_id tests**

In `tests/test_ref_resolution_secondary.py`, delete the functions `test_create_chore_parent_id_canonical_resolves`, `test_create_habit_parent_id_sequence_resolves`, and `test_create_event_parent_id_sequence_resolves`. Keep `test_create_task_parent_id_sequence_resolves` and `test_create_task_no_parent_id_no_resolve`. Update the module docstring's first bullet to:

```python
- ``create_task`` -- the ``parent_id`` arg (creation tools were excluded from
  #7). ``parent_id`` defaults to the unset sentinel, so it is resolved ONLY
  when a real ref is supplied (unset / None pass through untouched).
  (create_chore/habit/event were folded into capture_item, which carries no
  parent_id -- ADR-0003 keeps parent_id a create_task-only escape.)
```

- [ ] **Step 3: Run both affected suites**

Run: `python -m pytest tests/test_tools_contract.py tests/test_ref_resolution_secondary.py -v`
Expected: PASS — `test_tools_contract` no longer parametrizes `chores.create`/`habits.create`/`events.create`; the three deleted ref tests are gone; `create_task` ref tests still pass.

- [ ] **Step 4: Commit**

```bash
git add tests/spec/v0.1/chores/create.json tests/spec/v0.1/habits/create.json tests/spec/v0.1/events/create.json tests/test_ref_resolution_secondary.py
git commit -m "test(capture): drop create_* mcp_tool bindings + parent_id ref tests (ADR-0003)"
```

---

### Task 6: Docs — instructions, README, ADR-0003

**Files:**
- Modify: `src/defernowork_mcp/server.py:262-286` (`instructions`)
- Modify: `README.md` (behavioral-capture section from the prior session)
- Modify: `docs/adr/0003-behavioral-capture-caller-categorized-creation.md`

- [ ] **Step 1: Grep first, then update the server `instructions` blurb**

Run: `grep -rn "create_task / update_task for normal CRUD" tests/ src/`
If a test asserts that substring, update it alongside this step (surface it). Then in `server.py`, replace the sentence `"Use \`create_task\` / \`update_task\` for normal CRUD. "` with:

```python
        "To create any item, use `capture_item`: answer how it behaves "
        "(`attend`? `repeats`? `obligation` need-vs-want) and the server "
        "derives Task / Chore / Habit / Event. Use `create_task` directly only "
        "for a subtask under a parent, a `desire` score, or sequence chains; "
        "use `update_*` to edit an existing item. "
```

- [ ] **Step 2: Verify/align the README behavioral-capture section**

Read the `### Creating items (behavioral capture)` section of `README.md` (added last session). Confirm the documented signature matches the implemented one: params `title, attend, repeats, obligation ("need"/"want"), complete_by (ISO-8601 datetime), time_of_day (HH:MM), recurrence, description`; note `capture_item` has no `parent_id` and that `create_task` is the escape. Fix any drift (especially a `kind` arg, `if_missed`, a bare `date`, or `parent_id` on capture). Keep the Mermaid tree/truth table.

- [ ] **Step 3: Record the resolved wire mapping in ADR-0003**

In `docs/adr/0003-...md`, under **Consequences**, append:

```markdown
- **Wire mapping (verified against `Deferno/backend/src/payloads.rs` + deferno-kmp
  `CreatePayloadSerializationTest`):** `time_of_day` maps to `start_time_of_day`
  for an Event and `deadline_time_of_day` for Task/Chore/Habit; `complete_by` is
  a caller-supplied full datetime passed through verbatim, exactly as
  `create_task`/`create_event` already require -- the MCP does no timezone
  resolution (it has no ambient user tz; the backend keys off `complete_by`'s
  local date in the user's stored tz). The "split date + time_of_day" idea was
  dropped once the server-side tz cost surfaced; the bare-`date` form remains
  appropriate for device clients (deferno-kmp) that have the device tz.
- **Canonical-contract scope:** the cross-repo golden vectors
  (`tests/spec/capture/vectors.json`) pin the kind-derivation tree + field
  routing. The vectors are canonical **pending the KMP amend** -- `deferno-kmp`'s
  `CaptureInput` still carries the rejected `occursAtSetTime`; reconciling it is
  the follow-on in that repo.
```

- [ ] **Step 4: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all green). If `tests/test_server.py` asserts anything about the `instructions` text, reconcile (and surface it).

- [ ] **Step 5: Commit**

```bash
git add src/defernowork_mcp/server.py README.md docs/adr/0003-behavioral-capture-caller-categorized-creation.md
git commit -m "docs(capture): instructions + README + ADR-0003 mapping (ADR-0003)"
```

---

## Self-Review

**Spec coverage (ADR-0003):**
- Single `capture_item` front door, kind derived deterministically → Tasks 1–2. ✓
- 5→2 create tools (`capture_item` + `create_task`; remove the other three) → Tasks 2–3. ✓
- Three discriminators (`attend`/`repeats`/`obligation`), date/time orthogonal operands, source-not-a-signal → derivation in Task 1 (no source field exists in the schema, so source can't vote). ✓
- `derive_create_payload` defined and tested once + golden vectors fitting `tests/spec/` → Task 1. ✓
- `complete_by` caller-supplied (no MCP tz work), byte-for-byte with the existing create tools → Tasks 1–2. ✓
- Validation trust boundary (raises on malformed) → Task 1 `raises` vectors + Task 2 short-circuit test. ✓
- Advanced fields are a two-step `capture → update_*` flow → documented in the `capture_item` docstring + README (Tasks 2, 6). ✓
- `convert_item` safety net unchanged (not touched). ✓
- Lockstep marked canonical-pending-KMP → vectors `_doc` + ADR note (Tasks 1, 6). ✓

**Placeholder scan:** No "TBD"/"add validation"/"similar to Task N". Every code step shows full code; every test step shows the run command + expected result. ✓

**Type consistency:** `derive_create_payload(*, title, attend, repeats, obligation, complete_by, time_of_day, recurrence, description) -> tuple[str, dict]` is called with the identical keyword set in `tools/capture.py`. `CaptureError` raised in `capture.py`, imported and caught in `tools/capture.py` and asserted in `test_capture_derivation.py`. Wire keys (`complete_by`, `deadline_time_of_day`, `start_time_of_day`, `recurrence`) match the backend table verbatim. `register_capture(mcp, get_client, format_error)` 3-arg signature matches its `server.py` call site. ✓

**Out of scope (handoff items 2–7, by design):** occurrence-tool collapse (3b), plan/calendar dedupe (2), vocabulary concentration (1), the KMP repo amend (3), CONTEXT.md glossary (follow-on). This plan is candidate 3a only.
