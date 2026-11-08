# Secret & Data Scan — Evidence

> **Import-gate G3.** A named, ongoing, auditable secret scan plus the
> synthetic-only-data policy. The handover-evidence index (G10) links this doc.
>
> **Last updated:** 2026-06-13.

## Scanner

- **Tool:** [gitleaks](https://github.com/gitleaks/gitleaks) — a named, widely used
  secret scanner.
- **Version:** pinned to `8.30.1` in the CI workflow.
- **Ruleset:** gitleaks' full default ruleset (`[extend] useDefault = true` in
  [`.gitleaks.toml`](../../.gitleaks.toml)). No allowlist entries today — the
  committed tree is synthetic-only.

## How it runs (CI)

- **Workflow:** [`.github/workflows/secret-scan.yml`](../../.github/workflows/secret-scan.yml).
- **Triggers:** every `pull_request` (all branches) and every `push` to `main`.
- **What it does:** installs the pinned gitleaks CLI and runs
  `gitleaks dir . --redact --exit-code 1` over the committed tree. Any finding fails
  the job (and blocks the PR); `--redact` keeps matches out of the logs.
- **Portability:** uses the pinned CLI (not a marketplace action), so it needs no
  org license and carries cleanly into an adopting organization's CI.

## Result

- The committed tree is **synthetic-only by policy** (below); a manual pattern
  review found no credentials, keys, or tokens.
- The **CI `Secret Scan` workflow** runs the committed-tree scan on every PR and
  push to `main` — its passing run is the authoritative, ongoing evidence going
  forward (including the run on the PR that introduces this workflow).

## Allowlist

The config ([`.gitleaks.toml`](../../.gitleaks.toml)) extends gitleaks' default
ruleset with **no allowlist entries** today. Discipline: a justified `[allowlist]`
block is added only if CI surfaces a confirmed **non-credential** false positive;
no real or real-looking secret is silenced.

## Synthetic-only data policy

- **All committed fixtures, examples, and test data are synthetic.** No real
  customer data, production data, or PII is committed to this repository.
- Sample OpenAPI specs, manifests, field layouts, and authoring fixtures under
  `tests/` are illustrative, fabricated values only.
- Studio is a **local single-user web app**; runtime/session and generated output —
  `output/`, `GeneratedApps/`, `.edgeforge-studio-data/`, and the session JSON — are
  **git-ignored** and never committed.
- Studio externalizes any sibling-repo / Engine / Knowledge Server paths via
  environment configuration (see `README.md`); no secret values are committed.
- Any future real or PII data must **not** be committed; contributors use synthetic
  equivalents. The secret scan enforces the no-credentials half of this policy on
  every PR.

## Scope notes

- This is the **secret + synthetic-only-data** gate (G3). Heavier automated
  PII-detection tooling is out of scope here; the synthetic-only policy plus the
  named secret scan cover the "no real data / no secrets" import requirement.
- SBOM + dependency-license inventory is a separate gate (G4); the
  handover-evidence **index** is G10.
