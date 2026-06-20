# Round-2 agent-surface reduction: scope cull, sugar collapse, activity kind-merge

**Status:** accepted (extends the kind-neutral trajectory of
[ADR-0002](0002-compact-default-consolidated-read-surface.md) /
[ADR-0003](0003-behavioral-capture-caller-categorized-creation.md) /
[ADR-0004](0004-kind-neutral-item-mutation.md); **partially supersedes
ADR-0003's** retention of `create_task`)

The loaded tool surface is cut a second time — from **62 tools to 31** (the
planned 29, plus two Event-occurrence comment edit/delete tools the
verification gate forced us to retain — see Consequences) — by
asking, per tool, the question the earlier ADRs did not: *does an autonomous
agent drive this at all?* The cut has three moves: a **scope cull** of
human/admin/UI tools, a **sugar collapse** of convenience tools expressible from
primitives, and an **activity kind-merge** that extends the ADR-0003/0004
kind-neutral dispatch precedent to comments and attachments. The governing idea
is that the MCP exposes the **agent-relevant surface** — the capabilities an
agent acts on — not a 1:1 mirror of the human product surface.

This was scoped against a survey of how the target clients (Claude.ai
connectors over HTTP, Claude Code over stdio) and the broader harness ecosystem
handle tool context. Two findings framed it: server-driven dynamic tool
exposure (`notifications/tools/list_changed`) is **not** an available lever here
(Claude.ai connectors and the HTTP transport load the tool list once at session
start and never re-fetch; and a server cannot read agent intent, only its own
state); and client-side tool-RAG / deferral — the large win elsewhere — is
**not under this server's control** and is unreliable for HTTP/remote servers.
What remains fully under the server's control is the static surface itself.
Cutting whole tools is the only lever that reduces **both** token cost and tool
*count* (the latter matters: Cursor silently drops tools past ~40), with no
per-tool schema bloat and no agent-usability cost — because only unused
capability is removed.

## Move 1 — scope cull (the agent-relevant-surface line)

Removed because they serve a human-in-the-UI or admin workflow an agent does not
drive, not because they duplicate anything:

- **Admin / power-UI:** `list_feedback` / `feedback_stats` / `update_feedback`
  (admin-only product feedback), the saved-search CRUD (`list_` / `create_` /
  `update_` / `delete_` / `reorder_saved_search` — an agent runs `search_items`
  directly rather than persisting a query), and the sidebar-pin cluster
  (`list_pinned_tasks` / `reorder_pinned_tasks` / `update_pinned_label`, and the
  bare `set_item_pinned` toggle).
- **Bulk migration / niche read:** `import_data` / `export_data` (whole-account
  JSON backup/restore, a settings-page operation) and `get_mood_history`.
- **In-band auth / settings:** `start_auth` / `complete_auth` / `logout` /
  `get_settings` / `update_settings`. These are vestigial on both target
  transports — HTTP authenticates via the OAuth discovery flow (the server
  `instructions` already direct the agent there on a 401), stdio via the
  `defernowork-mcp auth` CLI command. **`whoami` is kept** as the one
  authentication-state probe an agent legitimately calls.

## Move 2 — sugar collapse

Removed convenience tools that add **no capability** an agent cannot compose from
the kept primitives; what they add is atomicity and one fewer round-trip:

- **`split_task` / `fold_task` / `merge_task`** — expressible as `capture_item`
  / `update_item` / `move_item` compositions.
- **`mark_next_chore_done`** — folds into `set_occurrence_status` as a dateless
  *"next / earliest-unresolved"* mode (chore-only); it was the one occurrence
  op ADR-0003 kept outside the ref+date model.
- **`get_items_plan`** — duplicate of `get_daily_plan`, which is kept (it is the
  seeded, carried-forward today-view and already spans all kinds).

`batch_tasks` is **kept** — its atomic, all-or-nothing multi-update/move is a
real guarantee a primitive loop cannot give.

### `create_task` is dropped, not folded

`create_task` overlaps `capture_item` on the simple-task case; it earned its
keep in ADR-0003 only for `parent_id` (subtask-under-a-parent), `desire`, and
sequence-chain fields. The tempting move — fold those fields onto `capture_item`
— is the **exact option ADR-0003 weighed and rejected** ("Extend `capture_item`
with `parent_id` / advanced fields … it would break the 1:1 cross-repo contract
that is the whole point of the shared derivation"). `capture_item`'s schema is a
frozen behavioral contract shared with `deferno-kmp` (`CaptureInput` /
`deriveCreatePayload`, pinned by `tests/spec/capture/vectors.json`); widening it
breaks that contract and re-introduces mode-conditional params (valid only when
the derived kind is Task).

So `create_task` is **removed entirely**, contract untouched: a parented create
becomes `capture_item` → `move_item`; a `desire` score or recurring chain
becomes `capture_item` → `update_item`. This pays the same −1 tool the fold
would, and accepts the two-call cost ADR-0003 spent the escape to avoid — a
usability call this reduction deliberately reverses.

## Move 3 — activity kind-merge (comments + attachments)

Comments and attachments exist as two parallel surfaces split by kind, the same
duplication `update_item` / `delete_item` removed for mutation:

- **item-level** (`post_item_comment`, `list_item_comments`,
  `presign_` / `commit_` / `list_` / `delete_item_attachment`,
  `set_item_attachment_caption`) — Task / Chore / Habit, addressed by a single
  ref, hitting `/items/{id}/…`.
- **Event-occurrence** (`post_` / `patch_` / `delete_event_occurrence_comment`,
  `presign_` / `commit_` / `list_` / `delete_event_occurrence_attachment`) —
  Events, addressed by `event_id` + occurrence `date`.

Five of the seven Event-occurrence tools are dropped; the kept item-level tools
gain an **optional occurrence `date`** and dispatch on resolved kind
(`resolve_ref_with_kind`): a ref that resolves to an Event with a `date` routes
to the per-occurrence backend call, every other case to `/items/{id}/…` — the
same client methods, one less surface. This is MCP-side dispatch over the
**existing** client methods, so it carries **no backend dependency** (unlike the
deferred `update_item` / `delete_item` unified-endpoint move, blocked on Deferno
#418 / #446).

**Implementation outcome:** the two Event-occurrence comment *edit/delete* tools
(`patch_` / `delete_event_occurrence_comment`) are **retained**, not dropped —
the pre-implementation verification gate (see Consequences) found occurrence
comments are not addressable by the generic `/comments/{id}` endpoints, so they
have no kind-neutral edit/delete path. The other five (the four attachment ops +
`post_event_occurrence_comment`) merged as planned. Net: 5 dropped, 2 kept → a
31-tool surface.

## Considered options

- **Fold `create_task` into `capture_item`.** Rejected — breaks the
  `deferno-kmp` behavioral-capture contract (see Move 2); dropping it gets the
  same surface win without the cross-repo breaking change.
- **A single `comment(operation=add|edit|delete|list, …)` enum tool.** Rejected.
  Comment operations have divergent param shapes (`add` needs a ref, `edit` /
  `delete` need a `comment_id`, the occurrence path needs `event_id` + `date`);
  an `operation` enum relocates that into one conditional union schema plus
  "required-when" prose — the `update_item` bloat pattern (1066 tokens) in
  miniature, with a model-accuracy cost. **Consolidate by shared *shape*** (the
  kind-merge, where target differs but params do not), not by topical grouping.
- **Server-driven dynamic tools via `notifications/tools/list_changed`** —
  expose a small core set and reveal the rest on demand. Rejected as
  non-viable for this server: the two target clients do not honor it
  (Claude.ai/HTTP load the tool list once per session), and a server cannot key
  tool exposure on agent intent — only on its own observable state (auth scope,
  prior calls), which does not align with which tools a turn needs.
- **Keep everything; rely on client-side tool-RAG / deferral.** Rejected as a
  primary strategy: deferral is the client's to give, is unreliable for
  HTTP/remote servers, and does nothing for clients that load all schemas
  upfront. Shrinking the static surface helps every client unconditionally.
- **Keep the convenience tools (`split`/`fold`/`merge`, `create_task`,
  `mark_next_chore_done`).** Rejected for surface concentration; the cost is
  extra round-trips and a small risk the agent mis-sequences a multi-step the
  sugar did atomically (e.g. a sequence chain `fold_task` preserved). Accepted
  knowingly. `batch_tasks` is the one exception kept, for its atomicity.

## Consequences

- **Breaking change:** clients calling any of the 31 removed tools migrate to
  the kept surface (`saved_searches` → `search_items`; `create_task` →
  `capture_item` ± `move_item` / `update_item`; `split`/`fold`/`merge_task` →
  primitive compositions; `mark_next_chore_done` → `set_occurrence_status`
  next-mode; Event-occurrence comment/attachment tools → the item-level tools
  with a `date`). Acceptable pre-1.0 (same precedent as ADR-0002/0003/0004).
- **Server `instructions` rewrite.** The preamble names `create_task` (for
  subtasks), the daily-plan tools, and the kind-neutral comment/attachment list;
  all must be updated to the new surface and flow. The instructions block is
  itself part of the per-session load cost (~491 tokens) and is worth a trim in
  the same pass.
- **Pre-implementation verification — comment edit/delete coverage. (RESOLVED:
  NO → 2 tools retained.)** Dropping `patch_` / `delete_event_occurrence_comment`
  is safe **only if** an Event-occurrence comment exposes a stable `comment_id`
  that the kept `update_comment` / `delete_comment` (`PATCH` / `DELETE
  /comments/{id}`) can target. The backend was checked: a `POST
  /events/{id}/occurrences/{date}/comment` pushes the comment onto the embedded
  `Occurrence.comment` Vec and **never writes the `embedded_comment:<id>`
  index** the generic `/comments/{id}` handlers resolve through — so those
  handlers **404** on an occurrence comment (the item-level
  `/items/{id}/comments` path *does* write that index; the per-occurrence POST
  does not). The two occurrence-comment edit/delete tools were therefore
  **retained** as the only edit/delete path (the fallback this gate named).
  A one-line backend change — `set_occurrence_embedded_comment_index(...)` at
  occurrence-POST time, mirroring the item-level path — would later make the
  generic endpoints work and let these two be dropped (tracked as a follow-up).
- **`set_occurrence_status` gains a conditional mode.** The dateless next-mode is
  chore-only, softening the clean "ref + date" addressing ADR-0003 established
  for occurrences. Narrow and documented, not a new pattern.
- **Cursor's ~40-tool cap is cleared** (31 < 40); tools no longer risk silent
  exclusion there.
- **CONTEXT.md follow-on (not done here):** if the kind-neutral comment +
  attachment tools are named as an **Activity surface**, that term — and the
  *agent-relevant surface* scoping line itself — are candidate glossary entries
  (each with an `_Avoid_` note), in the same spirit as ADR-0003's deferred
  capture-vocabulary follow-on.

## Token impact

Measured with `scripts/measure_tool_context.py` (Llama-3 BPE vocab) against the
implemented surface (snapshot `measure/final.json`):
**62 → 31 tools** and **13,427 → 9,396 tokens (−4,031, −30.0%)**. The 31 lands
two tools above the projected 29 because the verification gate forced retaining
`patch_` / `delete_event_occurrence_comment` (≈ +0.13k tok between them). The
kept tools that absorbed capability grew as expected: the item comment/attachment
tools' optional occurrence `date` dispatch (`post_item_comment` +64,
attachments +55…+97 each) and `set_occurrence_status`'s dateless chore next-mode
(+101). Server `instructions` net 526 tok (up from ~491 — the rewrite drops the
`split`/`fold`/`merge`/`create_task` prose but adds the occurrence-`date` and
comment edit/delete guidance for the retained tools). Cumulative from the
pre-PR-#19 88-tool surface: **21,506 → 9,396 (≈ −56%)**.
