# Deferno MCP Server

The MCP server and client that exposes the Deferno task manager to AI agents.
Its domain language is mostly **inherited from Deferno** — see
[`../Deferno/CONTEXT.md`](../Deferno/CONTEXT.md) for the item model (Task,
Habit, Chore, Event), Org model, and identifiers (Canonical ref, Sequence,
Alias, Item ID). This glossary captures only the terms that are specific to the
**agent-facing surface** of the MCP server — the vocabulary that does not exist
on the Deferno side.

## Language

### Identifier handling

**Ref input form**:
One of the identifier shapes the MCP accepts when an agent names a single item.
The recognised forms are **UUID**, **Sequence shorthand**, **Canonical ref**
(Deferno's `{org_slug}-{sequence}`), and **App URL**. The MCP classifies the
shape of an agent-supplied string and routes it to the matching Deferno lookup;
the agent never has to know which form it holds.
_Avoid_: id type, identifier kind (too generic).

**Transparent resolution**:
The MCP behaviour where *every* tool that takes an item identifier accepts any
[[Ref input form]] and resolves it to a UUID before acting. Required because
Deferno's mutation/operation endpoints are UUID-only — a non-UUID ref is always
resolved first, then the action runs against the resolved UUID. The agent
experiences a single identifier parameter that "just works."
_Avoid_: ref normalization (fuzzy — normalization is one step of resolution),
id coercion.

**Sequence shorthand**:
The `#123` (or bare `123`) [[Ref input form]]. Resolves against the user's
**personal org only**, by design — it is the per-org [[Sequence]] read in the
personal-org context. An item in a shared org cannot be named this way; use its
**Canonical ref** (`acme-123`) or **App URL** instead, which resolve across orgs.
_Avoid_: short id (ambiguous — Canonical ref is also "short"), issue number
(collides with the upstream-tracker sense once External tasks land).

**App URL**:
A `https://app.defernowork.com/o/{org_slug}/items/{seq-or-id}` link an agent can
paste verbatim as a [[Ref input form]]. The MCP extracts the org slug and
sequence (or UUID) from the path and resolves it like any other ref.
_Avoid_: deep link, permalink.

### Output shaping

**Compact projection** (a.k.a. **compact mode**):
The MCP's default trimmed shape for read and list results — a small, fixed set
of fields chosen so a query does not flood the agent's context. The full record
is available on demand via a `full` opt-out. Conceptually mirrors Deferno's own
default done-visibility window (bounded by default, full history on request).
_Avoid_: summary (collides with Deferno's `TaskSummary` wire struct), minimal,
slim.

## Flagged ambiguities

**"Issue #" — Deferno sequence vs upstream tracker**:
A bare `#N` today always means a Deferno [[Sequence shorthand]] in the personal
org. Once **External tasks** (GitHub issues; see Deferno's CONTEXT) land, the
same `#N` may instead name an upstream tracker issue, and `owner/repo#N` an
[[Alias]]. The intended end state is a **context-adaptive** classifier that
infers from the surrounding conversation which one the user means; until then
the MCP only auto-routes unambiguous forms and treats Alias lookup as an
explicit, opt-in path.

## Example dialogue

> **Agent**: The user said "mark #123 done." I have the string `#123`.
>
> **MCP author**: That's a [[Sequence shorthand]] — a [[Ref input form]]. You
> pass it straight to the status tool; [[Transparent resolution]] turns it into
> the item's UUID before the update runs. You don't fetch first.
>
> **Agent**: What if it's in a shared org?
>
> **MCP author**: `#123` only ever means the user's personal org. If the user
> meant a shared-org item, they'd give you the **Canonical ref** `acme-123` or
> an [[App URL]] — both resolve across orgs.
>
> **Agent**: They pasted `https://app.defernowork.com/o/u-1y0e2v/items/123`.
>
> **MCP author**: That's an [[App URL]]. Same thing — paste it as the id; the
> MCP pulls `u-1y0e2v` and `123` out of the path and resolves it.
