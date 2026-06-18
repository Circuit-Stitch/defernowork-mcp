# Caller-categorized item creation via a single behavioral capture tool

**Status:** accepted (supersedes the create-surface carve-out of
[ADR-0002](0002-compact-default-consolidated-read-surface.md))

Item creation is **caller-categorized**. A single `capture_item` tool takes a
small, jargon-free **behavioral schema** — the caller answers how the thing
*behaves*, never naming a Deferno [[Item kind]] — and the server
**deterministically derives** the kind (Task / Habit / Chore / Event) and builds
the kind-specific create payload. There is no inference and no model call on this
path: the kind is read straight off the discriminators. This collapses the four
per-kind create tools (`create_task` / `create_chore` / `create_habit` /
`create_event`) into one behavioral front door, directly serving the
tool-surface / context-window reduction this change set is about (the per-kind
create tools were among the heaviest schemas in the surface).

## The kind-derivation tree

Three orthogonal behavioral discriminators, answered from world knowledge:

```
Q1  Do you attend it?                         yes ──────────────► Event
     │ no                                     (attendance wins over recurrence)
Q2  Does it repeat on a schedule?             no ───────────────► Task
     │ yes
Q3  Does it NEED to happen (obligation),      need ─────────────► Chore
    or do you just WANT to at that interval?  want ─────────────► Habit
```

- **`Event` short-circuits first** — a thing you attend is an Event whether or
  not it repeats (a weekly stand-up is still an Event).
- **`need` vs `want` is asked only once we know it recurs.** Every one-off (want
  *or* need) is a **Task**; a Habit requires a recurrence cadence, so a one-off
  "want" has no valid Habit to land on. This is the same obligation-vs-aspiration
  split the Deferno backend encodes as *carries-forward* (Chore) vs *lapses*
  (Habit).

Two invariants keep the discriminators honest:

- **Date and time-of-day are orthogonal operands, never kind signals.** Per the
  Deferno unified-WHEN model (backend ADR 2026-06-10), *every* kind carries an
  explicit time-of-day — a deadline for Task/Chore/Habit, a start for Event — so
  "has a set time" cannot decide the kind. The kind is read off a behavioral
  answer, never inferred from an operand (the no-field-inference rule, Deferno
  ADR-0015).
- **Source never votes on kind.** An item originating from GitHub, Microsoft, or
  Google Calendar can be any of the four kinds; external provenance is orthogonal
  to the kind decision and is a contained, projection-local field (Deferno
  unified-item ADR 2026-04-22), not a discriminator.

## The create surface

- **`capture_item` is the single create front door.** It carries only the
  minimal capture schema (title, the three discriminators, optional
  date / time-of-day / recurrence / description) — exactly 1:1 with the
  cross-repo contract (below).
- **`create_chore` / `create_habit` / `create_event` are removed.**
- **`create_task` is retained as the one low-level escape.** It is the kind that
  most needs what capture deliberately omits: `parent_id` (subtask-under-a-parent
  creation), `desire`, and sequence-chain fields. Advanced recurring-kind fields
  (`subtask_template`, `cadence_mode`, recurrence `end`) are set with a follow-up
  `update_*` after capture, not at capture time.

Net: five create tools become two (`capture_item` + `create_task`).

## Cross-repo contract and its direction

The field→kind derivation tree is a **shared contract** with the
`deferno-kmp` client core (`CaptureInput` / `deriveCreatePayload`), per the
ADR-0036 amendment in that repo. **This MCP server leads it**: the MCP is the
live system and the KMP client is not yet shipped, so the schema is settled here
and KMP follows. This deliberately **inverts** ADR-0036's "`defernowork-mcp`
adopts the same … (mirror KMP)" framing — the inversion is the point, because the
discriminator below was *fixed* here, not inherited. The tree is the spec; drift
between the two implementations is a correctness bug, and the backend remains the
authority for the kind semantics the tree encodes (Deferno #231).

## Considered options

- **Keep the per-kind `create_*` tools (the [ADR-0002](0002-compact-default-consolidated-read-surface.md)
  carve-out).** ADR-0002 kept creation kind-specific "since creation is
  kind-specific." Rejected now: it bloats the tool surface (the very
  context-window cost being addressed) and forces the agent to hold Deferno's
  fine Habit-vs-Chore taxonomy. The behavioral schema is taxonomy-free and
  survives backend field churn.
- **Mirror KMP's `occursAtSetTime` discriminator verbatim.** Rejected: a settable
  start time is shared by *all four* kinds (unified-WHEN), so it cannot
  discriminate Event; and treating the not-yet-live KMP schema as the frozen
  authority is backwards. Replaced with the behavioral *attendance* discriminator.
- **Expose a `kind: ItemKind` enum to the caller** (one create tool, caller names
  the kind). Rejected: leans on a general agent grasping Deferno's taxonomy;
  brittle. The behavioral schema needs no taxonomy.
- **Keep all four `create_*` as escapes alongside `capture_item`.** Rejected:
  six create tools defeats the reduction goal. Keep only `create_task`.
- **`capture_item` only, no escape at all.** Rejected: loses first-class
  subtask-under-a-parent creation and Task-only fields (`desire`, sequence
  chains) agents use often; one escape earns its keep.
- **Extend `capture_item` with `parent_id` / advanced fields.** Rejected: it
  would break the 1:1 cross-repo contract that is the whole point of the shared
  derivation.

## Consequences

- **Breaking change:** clients calling `create_chore` / `create_habit` /
  `create_event` must migrate to `capture_item`. Acceptable pre-1.0 (same
  precedent as ADR-0002's removal of the task-only read tools).
- A single `derive_kind` / `derive_create_payload` function in the MCP, **defined
  and tested once**; kept in lockstep with `deferno-kmp` via shared golden test
  vectors (an input→expected-kind+payload fixture, fitting the existing
  `tests/spec/` pattern) — drift is a correctness bug.
- Advanced recurring-kind configuration becomes a **two-step flow** (capture, then
  `update_*`); this must be documented in the README and tool docstrings.
- The behavioral schema is a **versioned public surface** external callers bind
  to; changing a discriminator is a breaking change.
- The field→kind mapping **must track the backend's authoritative kind semantics**
  (Deferno #231 / unified-item / unified-WHEN). The edge is stable; the mapping is
  not frozen.
- `convert_item` remains the post-hoc safety net for a mis-derived capture.
- **Follow-ons (not decided here):** the `CONTEXT.md` glossary entries for the new
  vocabulary (*Behavioral capture*, *Kind derivation*, and the *Attendance /
  Recurrence / Need-vs-want* discriminators, each with an `_Avoid_` note — e.g.
  avoid "occurs at a set time"); and the kind-neutral occurrence-tool collapse
  (its addressing model — firing-id vs ref+date — and the Events-only reschedule
  constraint are still open).
