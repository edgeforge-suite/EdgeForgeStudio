# Contributing to EdgeForge Studio

> **This is the authoritative rules home for the EdgeForge Studio repository.** The
> tool-specific entry files — [`CLAUDE.md`](CLAUDE.md) and [`AGENTS.md`](AGENTS.md) —
> are thin pointers to this file and favor no single tool.

Read these before making meaningful changes:

- [`README.md`](README.md) — what Studio does, the wizard flow, how to run it.
- [`docs/studio-architecture.md`](docs/studio-architecture.md) +
  [`docs/studio-context.md`](docs/studio-context.md) — architecture source of truth
  and current baseline/handoff context.
- The Engine repository's `docs/suite-architecture.md` — suite orientation.

## What Studio is

A local, human-facing **FastAPI** web app that helps an author produce, review, and
locally run valid EdgeForge manifest packages. It captures intent, ingests upstream
specs, authors the CRUD / passthrough-router / kafka-integration flows, writes a
manifest package, and validates / generates / builds-and-runs **through the Engine**.
Studio orchestrates the Engine and Knowledge Server as local subprocesses.

## Non-Negotiable Invariants

- **Studio authors/reviews; the Engine generates.** Studio does **not** generate
  code or mutate generated apps directly — it writes manifest packages the Engine
  consumes.
- **Stay within the paired Engine manifest 2.0 contract.** Studio emits
  `schema_version: "2.0"` and does not carry a manifest-1.0 compatibility bridge.
  Don't broaden the passthrough-router (or any) wizard beyond the paired Engine
  schema/loader. The independently versioned Studio project snapshot remains 1.4.
- **Knowledge Assist is default OFF.** With KA OFF, surface no KS UI noise, stale
  drawer placeholders, subprocess-state leakage, or live KS calls. With KA ON, keep
  user intent separate from runtime KS process state.
- **Two runtime modes.** Defaults to **local single-user** (no auth). A **shared
  multi-session** mode (`EDGEFORGE_STUDIO_SHARED_MODE`) is available —
  per-principal SQLite session isolation, `max_projects_per_principal`, CSRF,
  audit, and fail-closed path confinement. Identity today is **anonymous
  per-session** (signed cookie); **real authentication (proxy/OIDC) is still
  deferred** — those adapters are interface placeholders for a later phase (auth
  delegates to the IdP/gateway when they land). Don't change the auth/isolation
  surface without a design gate.

## Repository Workflow Rules

- do not push or merge directly to `main`; all changes go through pull requests.
- expect parallel review branches from multiple AI agents.
- keep examples synthetic and exclude secrets and private employer/customer
  material. Necessary public dependency names, upstream references and attribution
  are permitted for accurate documentation and supported examples. Preserve the
  applicable source/distribution permissions, notices and modification disclosures;
  public attribution does not authorize private material.
- **no secrets and no real/production data** — fixtures and examples are synthetic
  only. Secret scanning runs in CI on every PR and push to `main`.

Recommended branch naming (`<agent>` is `claude`, `codex`, `devin`, or a human
name): `<agent>/feature/<short-description>`, `<agent>/fix/<short-description>`,
`<agent>/docs/<short-description>`, `<agent>/chore/<short-description>`.

Recommended PR title prefixes: `[FEATURE]`, `[FIX]`, `[DOCS]`, `[CHORE]`.

## PR lifecycle and ownership

GitHub Issues are authoritative for task ownership and progress. The Engine-owned
Suite roadmap sets direction; the tracker is a dated documentation view, not an
assignment board. A Project board is optional and does not replace issue ownership.

1. Before substantial work, comment on the owning issue with the proposed scope
   and obtain maintainer confirmation of ownership.
2. Open a focused draft PR linked to that issue. Explain the problem, resulting
   change, relevant validation and compatibility risks.
3. Mark the PR ready when implementation and relevant checks are complete.
   **Ready for review does not mean approved.**
4. Record review findings and their resolution in the PR. Identify the reviewed
   revision and review subsequent changes; an earlier approval does not
   automatically cover a new revision.
5. Maintainers retain merge control. Before merging, confirm applicable checks
   passed, required findings are resolved and the latest changes have been reviewed.
6. After merging, check applicable main-branch results and update the linked issue
   with the outcome; close it only when its work is complete. Delete completed
   branches only when they are no longer needed.

Recorded Claude/Codex review reports are review evidence, not formal GitHub
approvals. Identify the actual reviewer and reviewed revision. When the maintainer
also authored the PR, record their merge decision as a maintainer decision, not an
independent human approval. Preserve the existing independent-review approach and
any task-specific repair/re-review limits; this process adds no universal second
review, new release gate or reset of an existing allowance.

## Setup, Build, Test

Python **3.11+** is required.

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -c constraints.txt pip setuptools wheel
.venv/bin/python scripts/verify-packaging-toolchain.py
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
.venv/bin/uvicorn app.main:app --reload --port 8080   # then open http://localhost:8080
.venv/bin/python -m pytest tests/ -v
```

A `Makefile` exposes `make setup` / `make run` / `make test` / `make sbom`. A Docker
Compose dev runtime is also available (see [`README.md`](README.md)).

## Guidance For Reviews And Changes

### Before opening an issue or contribution

See [project intent and community](README.md#project-intent-and-community) for
ordinary questions, feedback and the maintainer's service boundaries.

Read [SECURITY.md](SECURITY.md) first for suspected vulnerabilities; do not post
undisclosed vulnerabilities publicly. For ordinary bugs, use the bug template
with a minimal synthetic reproduction, Studio/Engine revisions, runtime mode,
KA state and relevant tool versions. Redact logs, cookies, tokens, identities,
host paths and uploaded content. Prefer the maintained sample packs; explain
what was changed and what was expected versus observed. Feature requests should
describe the authoring problem, supported contract and measurable outcome.

Source terms are [Apache-2.0](LICENSE); see [NOTICE](NOTICE). Contributions use
the [Developer Certificate of Origin 1.1](https://developercertificate.org/),
not a CLA. Contributors must certify their own right to submit each contribution
by adding a `Signed-off-by: Your Name <your-email>` trailer (`git commit -s`).
Do not sign on behalf of another person, remove third-party notices, or submit
material you cannot license under the project terms. The DCO does not transfer
copyright. Maintainer publication authorization remains a separate pending gate.

The selected contribution destination is
[edgeforge-suite/EdgeForgeStudio](https://github.com/edgeforge-suite/EdgeForgeStudio);
its activation/public availability is not established by this private PR.
CODEOWNERS remains a commented template, not enforced ownership. The
[publication record](docs/publication-preparation.md) holds the remaining gates
and two unpublished starter drafts. Existing private pre-v5 issue #302
tracks A11y-01; it is accessible only to authorized repository readers while
Studio remains private. Contributor help does not transfer Studio's ownership.

### Preparing and reviewing a PR

Keep one bounded change per PR and link its approved issue/design when needed.
State scope, user-visible result, limitations and affected Studio/Engine
contracts. Include commands actually run, results and reasons for omitted
checks. Prose-only corrections do not need new tests that merely assert wording;
behavior changes need regression coverage. Keep setup instructions and the
newcomer guide's proven flow consistent without expanding their claims.

Reviewers should independently inspect the diff and supporting source, reproduce
material claims where feasible, and record the exact reviewed SHA, findings,
checks and exclusions. Green CI does not establish broader Suite/runtime or
accessibility acceptance. Any fix commit needs applicable CI and review of the
new SHA; human merge remains required. Do not merge your own agent PR, publish
issues, change settings, or authorize release as a side effect of a contribution.

- prefer small, reviewable changes; preserve the paired manifest 2.0 contract boundary
  above all, and call out any compatibility risk to exported packages explicitly.
- keep the KA-OFF default behavior intact when touching Knowledge Assist surfaces.
- some tests are **integration tests** that need a local Engine checkout (and JDK/
  Maven for Build & Run); note when a change affects those paths.
