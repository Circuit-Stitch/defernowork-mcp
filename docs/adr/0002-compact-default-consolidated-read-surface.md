# Compact-by-default output and a consolidated, item-model read surface

**Status:** accepted

Read and list tools return a [[Compact projection]] by default — a small fixed
field set — with a `full=true` opt-out for the complete record; list tools also
take an explicit `limit`. Lists shrink the payload **at the wire** via the
backend's OData `$select`/`$top`/`window` on `GET /items` (the handler injects
`ref`/`org_slug`/`type`/`sequence` into every row regardless of `$select`), not
just by trimming MCP-side. In the same move the read surface is **consolidated**
onto Deferno's unified item model: kind-neutral `list_items` / `search_items` /
`get_item` are added and the tasks-only, personal-org-only `list_tasks` /
`get_task` / `search_tasks` are removed; kind-specific *mutations*
(`create_task`, `create_event`, …) stay, since creation is kind-specific.
Resources are trimmed to naturally-bounded surfaces (the unbounded
`defernowork://tasks` is dropped) because some clients auto-load resources into
context unprompted.

This is driven by the agent-usability goal: an unbounded, full-detail dump fills
an agent's context window, and a tasks-only list is blind to the other three
item kinds and to shared orgs.

## Considered options

- **Add item tools alongside the task tools (no removal).** No breakage, but
  grows the tool list (itself a context cost) and leaves two ways to list.
  Rejected in favour of a smaller, item-model-aligned surface.
- **Verbosity enum (`summary`/`standard`/`full`).** Finer control, but a richer
  API to document and for the agent to choose between. Rejected for a simple
  two-tier boolean.
- **Caller-specified `fields` with full default.** Does nothing for the
  default-bloat problem unless the agent remembers to opt out. Rejected.

## Consequences

- **Breaking change:** clients calling `list_tasks` / `get_task` / `search_tasks`
  must migrate to the item tools. Acceptable while the MCP is still pre-1.0.
- `get_item`'s compact form omits heavy arrays (action history, mood vectors);
  those keep their dedicated tools (`get_item_history`, `get_mood_history`).
- The README and tool docstrings (which today document only the task tools and
  the dropped resources) must be rewritten to match.
