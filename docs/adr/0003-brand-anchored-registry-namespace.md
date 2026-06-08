# Brand-anchored MCP Registry namespace, decoupled from the source host

**Status:** accepted

The server's published identity in the official MCP Registry is
`com.defernowork/defernowork-mcp` — a DNS-verified namespace anchored to the
brand domain `defernowork.com`, not to the GitHub account that hosts the source.
Source moves to the `Circuit-Stitch` GitHub org (where Deferno projects now
live), but the GitHub org is treated as **source host only** and does not define
the registry identity. The same name is embedded as the `mcp-name` in the
published PyPI package and carried in `server.json`, so the registry can verify
ownership of every distribution form (remote endpoint, PyPI, OCI image).

Anchoring identity to the brand domain keeps three identities distinct and
independently movable: brand (`defernowork.com`), source host (`Circuit-Stitch`
on GitHub), and legal entity (Circuit-Stitch).

## Considered options

- **GitHub namespace `io.github.<org>/defernowork-mcp`.** Zero infrastructure —
  verified just by signing into `mcp-publisher` as the repo owner. Rejected: the
  identity is tied to the GitHub handle, so the in-flight transfer from
  `kyle-falconer` to `Circuit-Stitch` (and any future org move) would orphan the
  published name. The move we are making right now is the exact failure mode.
- **DNS namespace `work.deferno/...`.** Same mechanism, alternate domain.
  Rejected: `defernowork.com` is the canonical brand and `app.defernowork.com`
  is already the live product surface; `deferno.work` is not the steered brand.

## Consequences

- A DNS TXT record on `defernowork.com` is required for namespace verification
  before the first registry publish.
- The repo transfer to `Circuit-Stitch` breaks anything bound to the old
  location and must be fixed in lockstep: the **PyPI trusted publisher** (OIDC is
  bound to `owner/repo`), the **GHCR image path** in `release.yml` /
  `docker-compose.prod.yml`, and the repo URLs in `pyproject.toml` / README.
- `server.json` and the PyPI metadata must carry `com.defernowork/defernowork-mcp`
  verbatim; a mismatch fails registry ownership validation.
