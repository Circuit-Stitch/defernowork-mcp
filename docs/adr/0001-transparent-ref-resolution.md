# Transparent ref resolution in every id-taking tool

**Status:** accepted

Every MCP tool that takes an item identifier accepts any [[Ref input form]]
(UUID, `#123`/bare sequence, canonical ref `slug-123`, or an app URL) and
resolves it to a UUID before acting, because Deferno's mutation and operation
endpoints (`PATCH /tasks/{id}`, `/items/{id}/move|split|merge|convert|pin`,
`DELETE …`) are all `Path<Uuid>` — only the `GET /items/by-ref|by-seq|by-alias`
read routes accept human forms. So a ref is always resolved first, then the
action runs against the resolved UUID. `#123` (and bare `123`) resolve against
the user's **personal org only**, matching the backend's `by-seq` semantics;
shared-org items must be named by canonical ref or URL, which resolve across orgs.

## Considered options

- **Explicit `resolve_ref` tool, all other tools UUID-only.** Cleaner contract,
  no hidden round-trips — but the agent must resolve first and will forget,
  producing confusing "expected UUID" errors. Rejected: the whole point is that
  an agent can paste whatever identifier it has.
- **Org-aware `#123`** (an `org=` param, or a backend change so `by-seq` takes an
  org). Rejected for now: the canonical ref already disambiguates every cross-org
  case, and personal-org-only `#123` matches the backend exactly with no new
  surface.

## Consequences

- A mutation given a non-UUID ref costs one extra resolve round-trip. Acceptable.
- Tool docstrings must stop saying "(UUID)" and state that any ref form is accepted.
- The classifier only auto-routes **unambiguous** forms. `owner/repo#N`-style
  aliases and the broader "is this a Deferno sequence or an upstream issue?"
  disambiguation are deferred to a context-adaptive follow-on (see CONTEXT.md
  "Flagged ambiguities").
