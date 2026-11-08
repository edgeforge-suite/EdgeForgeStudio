# EdgeForge Studio — Agents (Codex / Devin / general)

EdgeForge **Studio** — the local, human-facing **FastAPI** companion app for the
EdgeForge Engine. Authors capture intent, ingest upstream specs, and produce/review
valid EdgeForge **manifest packages**, then validate / generate / build-and-run the
generated app locally **through the Engine**. Studio orchestrates the Engine and
Knowledge Server as local subprocesses; it does **not** generate code itself — the
Engine owns generation.

## Start here

- **Authoritative rules — read before changing anything:**
  [`CONTRIBUTING.md`](CONTRIBUTING.md)
- **Architecture / orientation:** [`docs/studio-architecture.md`](docs/studio-architecture.md)
  + [`docs/studio-context.md`](docs/studio-context.md); the suite map lives in the
  Engine repository's `docs/suite-architecture.md`.
- **Branch / PR conventions:** see [`CONTRIBUTING.md`](CONTRIBUTING.md)
  (`<agent>/{feature|fix|docs|chore}/<short-desc>`; PR title prefix
  `[FEATURE]` / `[FIX]` / `[DOCS]` / `[CHORE]`).

## Invariants (do not break)

- **Studio authors/reviews; the Engine generates.** Studio never generates code or
  mutates generated apps directly.
- **Stay within the paired Engine manifest 2.0 contract** — Studio emits
  `schema_version: "2.0"` with no manifest-1.0 bridge; don't broaden beyond the
  paired CRUD / passthrough-router / kafka-integration contracts.
- **Knowledge Assist is default OFF.** With KA OFF there is no KS UI noise, stale
  drawer state, subprocess-state leakage, or live KS calls.
- **Two runtime modes.** Defaults to **local single-user** (no auth). A **shared
  multi-session** mode (`EDGEFORGE_STUDIO_SHARED_MODE`) ships with per-principal
  SQLite session isolation, CSRF, audit, and path confinement. Identity today is
  **anonymous per-session** (signed cookie); **real authentication (proxy/OIDC)
  is still deferred** — those adapters are interface placeholders for a later
  phase. Don't change the auth/isolation surface without a design gate.
- **No secrets or real/production data** committed — synthetic fixtures only.

---

*This file is a thin, tool-specific pointer. The canonical rules live in
[`CONTRIBUTING.md`](CONTRIBUTING.md) — keep it in sync, don't fork it.*
