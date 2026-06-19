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
    if complete_by is None:
        raise CaptureError(
            "a repeating Chore/Habit capture requires complete_by (the series "
            "start) -- the backend requires it for /chores and /habits"
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
