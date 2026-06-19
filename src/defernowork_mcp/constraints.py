"""Shared, human-readable descriptions of backend-enforced constraints.

These strings are surfaced *proactively* on tool docstrings and parameter
schemas (issue #13) so an LLM client gets input right on the first try, with
the reactive backend 400 as the backstop. Centralised here so every tool that
takes the same field documents the same rule, word-for-word.
"""

from __future__ import annotations

# Recurrence bound, per ADR 2026-06-02 (recurrence-anchor-and-bound): the
# series is anchored at the chosen start (``complete_by``), and an ``on_date``
# end earlier than that anchor is rejected (empty series). Same-day is allowed
# because ``on_date`` is inclusive of the whole local day.
RECURRENCE_END_DESC = (
    "Repeat schedule: a cadence (e.g. `{type: daily}`, "
    "`{type: every_n_days, n: 3}`, `{type: weekly, days: [Mon, Wed]}`) plus an "
    "optional bound under `end`. If `end` is `{type: on_date, date}`, that date "
    "must be on or after the series start (`complete_by`'s local calendar "
    "date); same-day is allowed — the backend rejects an earlier end with a "
    "400. `{type: after_count, n}` (n >= 1) or an omitted `end` is open-ended."
)

# Event end >= start, reaffirmed on the param schema AND the docstring (issue
# #13): the backend rejects an event whose end precedes its start with a 400.
EVENT_END_TIME_DESC = (
    "Event end (ISO-8601). When provided, `end_time` must be on or after "
    "`complete_by` (the event's start); the backend rejects it with a 400 "
    "otherwise."
)
