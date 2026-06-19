# Kind-neutral item mutation: `update_item` and `delete_item`

**Status:** accepted (extends the kind-neutral trajectory of
[ADR-0002](0002-compact-default-consolidated-read-surface.md) /
[ADR-0003](0003-behavioral-capture-caller-categorized-creation.md); same
dispatch precedent as the occurrence collapse)

The four per-kind edit tools (`update_task` / `update_chore` / `update_habit` /
`update_event`), the four per-kind delete tools (`delete_task` / `delete_chore`
/ `delete_habit` / `delete_event`), and the `set_task_status` convenience
collapse into **two kind-neutral tools**: `update_item` and `delete_item`. Each
resolves any [[Ref input form]] to `(uuid, kind)` via `resolve_ref_with_kind`
and dispatches to the matching per-kind backend call — the exact primitive the
occurrence tools already use. This is the *edit/delete* analogue of ADR-0003's
`capture_item` (which did the same for *creation*), and removes the largest
remaining duplication in the loaded tool surface.

## The dispatch

`update_item(ref, …)` resolves the kind, validates fields against it at the
**trust boundary** (before any write — mirroring `capture_item`'s create path),
then PATCHes the per-kind entity path:

- **Shared fields** (all kinds): `title`, `description`, `complete_by`,
  `labels`, `recurrence` (with the same recurrence-end ≥ series-start bound).
- **Task-only**: `status`, `assignee`, `productive`, `desire`, and the
  recurring-Task controls `recurring_scope` / `recurrence_id` / `recurring_type`.
  The recurring-Task **scope guard** (a deferno-field change on a series-backed
  task with no scope returns the ask-for-scope message instead of writing) moves
  verbatim into the task branch.
- **Event-only**: `end_time` (≥ `complete_by`).
- A Task-only field on a non-Task, or `end_time` off an Event, is rejected with
  a clear message and **no** HTTP write.

`delete_item(ref)` resolves the kind and dispatches to the per-kind DELETE,
**preserving the existing semantics**: a Task is hard-deleted; a Chore / Habit /
Event is archived (soft-delete). It returns `{deleted, id, kind}`.

## Considered options

- **Wire `delete_item` to the unified `DELETE /items/{id}`.** The backend
  exposes a kind-neutral delete, which would need no kind dispatch. Rejected:
  its hard-vs-soft semantics are unverified against the per-kind behavior (Task
  hard-delete vs the others' archive), and silently changing delete semantics is
  not worth one fewer round-trip. Dispatching per-kind preserves exact behavior;
  collapsing onto the unified endpoint can be revisited once the backend
  contract is confirmed equivalent.
- **A unified `PATCH /items/{id}`.** Does not exist on the backend — update is
  per-kind, so `update_item` must dispatch (unlike a hypothetical single-endpoint
  passthrough).
- **Keep `set_task_status`.** Rejected: it is a pure pass-through of
  `update_item(ref, status=…)`; keeping it contradicts the surface-concentration
  goal it was measured to cost (152 tokens).
- **Expose a `kind` parameter to the caller.** Rejected for the same reason
  ADR-0003 rejected it for creation: it leans on the agent holding Deferno's
  taxonomy. The kind is resolved from the ref, not supplied.

## Consequences

- **Breaking change:** clients calling `update_*` / `delete_*` / `set_task_status`
  migrate to `update_item` / `delete_item`. Acceptable pre-1.0 (same precedent as
  ADR-0002 / ADR-0003).
- `update_item` carries a **union schema** with per-kind-validated fields — a
  wider single interface, but one tool instead of five. The `habits.py` and
  `events.py` tool modules emptied out and were deleted; `chores.py` keeps only
  `mark_next_chore_done` (no ref+date kind-neutral equivalent).
- A raw **UUID** ref now pays one `GET /items/{id}` to discover the kind (the
  documented `resolve_ref_with_kind` cost; a non-UUID ref learns the kind free
  from its resolve round-trip). For the recurring-Task scope-guard path a UUID
  task pays one additional `GET /tasks/{id}` — narrow and acceptable.
- Retired tools' **backend endpoints and client methods stay** (the client still
  exposes `update_chore`, `delete_event`, …; `update_item` dispatches to them).
  Their spec fixtures keep `client_method` and null `mcp_tool`, exactly as the
  PR-#19 retirements did — the inventory cross-check is endpoint-based and stays
  green. Tool-layer coverage moves to `tests/test_ref_resolution_item_mutations.py`.
- ADR-0002's "kind-specific **mutations** stay, since creation is kind-specific"
  was a rationale about *creation*; it no longer governs *update/delete*, which
  act on an already-existing item whose kind is resolvable.

## Related change — per-tool ref-pointer de-duplication

Shipped alongside: the per-parameter line *"accepts any item ref (UUID / `#123`
/ `acme-123` / app URL; see instructions)"*, repeated across ~33 docstrings, is
removed in favor of the single canonical statement already in the server
`instructions` (per [ADR-0001](0001-transparent-ref-resolution.md), [[Transparent
resolution]] is a global invariant of *every* id-taking parameter). Each
parameter keeps a short "is any item ref" hint. This goes one step past PR #19's
"vocabulary concentration" (which kept a one-line pointer per param); the fact
now lives in exactly one place. **Locality:** the identifier vocabulary has a
single source of truth.

## Token impact

Measured with `scripts/measure_tool_context.py` (Llama-3 BPE vocab): the loaded
surface drops **15,880 → 13,427 tokens (−15.4%)** and **69 → 62 tools** — about
−1,923 from the update/delete collapse and ~−530 from the ref-pointer
de-duplication. Cumulative from the pre-PR-#19 88-tool surface: 21,506 → 13,427
(−37.6%).
