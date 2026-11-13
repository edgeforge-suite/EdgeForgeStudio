# Security Policy

## Reporting a vulnerability

- **Do not** open a public issue or pull request for an undisclosed
  vulnerability.
- Use GitHub Private Vulnerability Reporting (PVR)
  **when available**:
  [Report a vulnerability](https://github.com/edgeforge-suite/EdgeForgeStudio/security/advisories/new).
  Confirm that the destination visibly opens a private report.
- The designated security email is **`security@edgeforgesuite.com`**.
- If neither route is available, request a private maintainer channel without
  including vulnerability details in a public issue or PR. Share technical
  details and sensitive logs only through an available private route.
- Include: affected component (a route/endpoint, a service, the upload path, the
  Engine/KS integration), version/baseline or commit, reproduction steps, and impact.

Reporting-route delivery/reply checks and PVR verification are part of the
public-cutover requirements in the decision record below; listing a route does
not establish that those checks have run. No response-time commitment
or support SLA is set here. Old pre-v5 private issue links are not reporting routes.
See the [single decision record](docs/publication-preparation.md#remaining-maintainer-decisions).

## Supported versions

Security fixes target the **current suite baseline** (see [`README.md`](README.md)
and [`CHANGELOG.md`](CHANGELOG.md)). Older tags are not separately maintained.

## Scope notes

- **Local single-user mode** is the default: no authentication, localhost only,
  with operator-directed Engine and optional Build & Run subprocesses.
- **Shared multi-session isolation ships:** anonymous signed-session identity,
  per-session SQLite state/workspaces, CSRF, audit, quotas and confined Engine
  calls. It is single-replica; Build & Run is disabled by default. This is not
  real user authentication: proxy/OIDC adapters and RBAC integration remain
  deferred. See the [operator contract](docs/deployment-model.md).
- **Untrusted input it handles:** uploaded / pasted / URL-fetched OpenAPI specs and
  authoring input. A report should say which path reproduces.
- **Studio authors; the Engine generates.** Studio does not generate code; it
  orchestrates the Engine and Knowledge Server as local subprocesses. Report a
  generation-side issue against the Engine where it reproduces.
- **No secrets or real/production data** should ever be committed (synthetic-only
  policy). Secret scanning runs in CI on every PR and push to `main`.
- This repository is part of a multi-repo suite (Engine, Studio, Knowledge Server).
  Report against the repository where the issue reproduces; cross-repo issues can be
  noted in the report.
- Knowledge Assist is optional and OFF by default. Knowledge Server is a separate
  optional local process; a KS-side report belongs with its maintainer.
- Uploaded/pasted material is not sanitized and may be retained in project state,
  Knowledge Workspace storage and exported packages. Use synthetic or approved
  content, and redact diagnostics before sharing.
- Dated [image evidence](docs/handover-evidence/README.md) retains open findings,
  scanner exclusions and vendor-copy coverage limits. A Python audit or a green
  documentation PR does not clear the image or establish Suite acceptance.
