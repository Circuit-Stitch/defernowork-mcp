"""Issue #13: create/update tools document temporal constraints up front.

Two constraints are enforced server-side (a 400 on violation):

- **Recurrence end** — if ``recurrence.end`` is ``{type: on_date, date}``, that
  date must be on or after the series start (``complete_by``'s local calendar
  date); same-day is allowed (ADR 2026-06-02 recurrence-anchor-and-bound).
- **Event ``end_time``** — must be on or after ``complete_by``.

The MCP already surfaces these *reactively* (the tool catches ``DefernoError``
and returns the formatted 400). This pins the *proactive* half: the constraint
appears in BOTH the tool's docstring (the LLM-visible ``description``) AND the
parameter's JSON-schema ``description`` — so a client gets it right first try,
with the reactive 400 as the backstop.
"""

from __future__ import annotations

import pytest

from defernowork_mcp import server as srv

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

# Stable substrings — phrasing may evolve but these anchors must remain.
RECURRENCE_END_PHRASE = "on or after the series start"


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(srv, "_http_transport_mode", False)
    return srv.create_server()


def _tool(mcp, name):
    tools = getattr(mcp, "_tool_manager", None) or getattr(mcp, "tool_manager", None)
    for attr in ("_tools", "tools"):
        tool_map = getattr(tools, attr, None)
        if isinstance(tool_map, dict) and name in tool_map:
            return tool_map[name]
    raise LookupError(f"tool {name!r} not registered")


def _norm(text: str) -> str:
    """Collapse all whitespace runs to single spaces.

    Docstrings are hand-wrapped at ~79 cols, so a phrase like "the series
    start" can straddle a newline. The constraint being *documented* is what
    matters, not where the line breaks fall — so we match on normalized text.
    """
    return " ".join((text or "").split())


def _param_schema(tool, param):
    return tool.parameters.get("properties", {}).get(param, {})


# ── recurrence-end >= series start ────────────────────────────────────────────


@pytest.mark.parametrize("name", RECURRENCE_TOOLS)
def test_recurrence_end_constraint_in_docstring(server, name):
    tool = _tool(server, name)
    assert RECURRENCE_END_PHRASE in _norm(tool.description), (
        f"{name} docstring does not document recurrence-end >= start"
    )


@pytest.mark.parametrize("name", RECURRENCE_TOOLS)
def test_recurrence_end_constraint_in_recurrence_param_schema(server, name):
    tool = _tool(server, name)
    desc = _norm(_param_schema(tool, "recurrence").get("description", ""))
    assert RECURRENCE_END_PHRASE in desc, (
        f"{name} recurrence param schema has no recurrence-end constraint description"
    )


# ── event end_time >= complete_by ─────────────────────────────────────────────


@pytest.mark.parametrize("name", EVENT_TOOLS)
def test_end_time_constraint_in_docstring(server, name):
    tool = _tool(server, name)
    d = _norm(tool.description)
    assert "end_time" in d and "complete_by" in d and "on or after" in d, (
        f"{name} docstring does not document end_time >= complete_by"
    )


@pytest.mark.parametrize("name", EVENT_TOOLS)
def test_end_time_constraint_in_param_schema(server, name):
    tool = _tool(server, name)
    desc = _norm(_param_schema(tool, "end_time").get("description", ""))
    assert "complete_by" in desc and "on or after" in desc, (
        f"{name} end_time param schema has no >= complete_by constraint description"
    )


# ── guard: documenting a constraint must not flip the param to required ───────


@pytest.mark.parametrize("name", RECURRENCE_TOOLS)
def test_recurrence_param_stays_optional(server, name):
    """Adding ``Field(description=...)`` must not make ``recurrence`` required.

    The contract tests invoke ``tool.fn(**kwargs)`` directly, bypassing schema
    validation — so an optional->required flip would otherwise go uncaught.
    """
    tool = _tool(server, name)
    assert "recurrence" not in (tool.parameters.get("required") or [])


@pytest.mark.parametrize("name", EVENT_TOOLS)
def test_end_time_param_stays_optional(server, name):
    tool = _tool(server, name)
    assert "end_time" not in (tool.parameters.get("required") or [])
