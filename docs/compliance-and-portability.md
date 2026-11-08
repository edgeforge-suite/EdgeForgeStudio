# Compliance & Portability Checklist — Studio

> **Import-gate G7.** A reviewer's answer-sheet: the questions an import / compliance
> review asks, each **pre-answered and linked to real evidence** — with honest
> caveats where something is pending or nuanced. Claims about code were **verified
> against the source** (the method is stated where it matters), not asserted.
>
> **Two deployment postures.** Studio ships **local single-user** (default) and
> **shared multi-session** (`EDGEFORGE_STUDIO_SHARED_MODE=true`). Compliance answers
> that differ by posture are marked **[local]** / **[shared]**. The operator contract
> is [deployment-model.md](deployment-model.md); the architecture is
> [security-boundary-map.md](security-boundary-map.md) (G8).
>
> **Last updated:** 2026-06-17. This checklist **links** the evidence pack (G3 secret
> scan, G4 SBOM/licenses) as the single source of truth; it does not re-derive it.
> The G10 [handover-evidence index](handover-evidence/README.md) links this doc.

**Publication clarification (2026-10-10):** the original import framing below is
retained, but public-source terms and a verified security route are project
maintainer responsibilities. Current exceptions and ownership are recorded
[once here](publication-preparation.md#remaining-maintainer-decisions). The
dated evidence is not refreshed by editing this answer-sheet.

## At a glance

| # | Question | Short answer | Evidence |
|---|---|---|---|
| 1 | License posture | Apache-2.0 / Santosh Hommaradi and DCO 1.1 are selected; publication authorization and third-party obligations remain separate gates | [§1](#1-license-posture) |
| 2 | Secrets / real data | No secrets; named scan enforced in CI; all data synthetic; output/session/catalog git-ignored | [§2](#2-secrets-and-real-data) |
| 3 | Telemetry / phone-home | No Studio telemetry/analytics found; user-directed URL fetch and dependency/build tooling can need network access | [§3](#3-telemetry-and-phone-home) |
| 4 | Standalone / coupling | Authoring tool; orchestrates Engine/KS as local subprocesses; no hosted-service dependency; authored apps don't depend on Studio | [§4](#4-standalone-and-no-runtime-coupling) |
| 5 | Data-handling posture | **[local]** single-user, all local. **[shared]** per-session isolation, identity seam, audit + ownership, retention; KA **OFF** by default (no LLM) either way | [§5](#5-data-handling-posture) |
| 6 | Dependency hygiene | Pinned `requirements.txt`; reproducible SBOM; single Python stack | [§6](#6-dependency-hygiene) |
| 7 | Portability | Python 3.11+, FastAPI/uvicorn; Docker option; air-gappable (use upload/paste) | [§7](#7-portability) |
| 8 | Shared-service deployment | Single-replica anonymous session isolation; real proxy/OIDC identity and RBAC integration deferred; Build & Run off by default | [§8](#8-shared-service-deployment-posture) |

---

## 1. License posture

**Third-party dependencies:** all declared dependencies are permissive (MIT / BSD /
Apache-2.0) — no copyleft. Inventory + machine-readable SBOM:
[`dependency-licenses.md`](handover-evidence/dependency-licenses.md) ·
[`sbom.cdx.json`](handover-evidence/sbom.cdx.json) ·
[`dependencies.md`](handover-evidence/dependencies.md) (G4).

**Studio's own license:** [Apache-2.0](../LICENSE), copyright Santosh Hommaradi;
see [NOTICE](../NOTICE). Inbound contributions use DCO 1.1, not a CLA. These
maintainer-approved source-preparation terms do not establish authority to
publish, activate reporting routes or relicense third-party code.
See the [current preparation record](publication-preparation.md#current-private-source-preparation---2026-10-25).

> **Dated scope:** declared and transitive inventories are committed. The
> 2026-09-30 transitive record flags `caio` (UNKNOWN) and `certifi` (MPL-2.0).
> Neither the declared summary nor a Python inventory resolves licenses for the
> image's OS/JDK/Maven contents or grants rights in generated applications.
> Follow the [evidence index](handover-evidence/README.md) for provenance and limits.

## 2. Secrets and real data

**No secrets in the repository, enforced on every change.** A named secret scanner
(**gitleaks**, pinned) runs in CI on every PR and push to `main`; the committed tree
scans clean.

**All fixtures/examples are synthetic** — no real customer data or PII is committed
(synthetic-only-data policy). Runtime state and generated output (`output/`,
`GeneratedApps/`, `.edgeforge-studio-data/`, the session JSON, and — in shared mode —
the SQLite session/project catalog and per-session workspaces under the state dir) are
**git-ignored** and never committed. Sibling-repo / Engine / KS paths are
env-configured, not committed.

Evidence: [`secret-and-data-scan.md`](handover-evidence/secret-and-data-scan.md) and
the [`secret-scan` workflow](../.github/workflows/secret-scan.yml) (G3).

## 3. Telemetry and phone-home

**Verified result: Studio has no telemetry, analytics, or phone-home.**

**Verification method (reproducible):** a grep of `app/**` for telemetry/analytics
SDKs (`sentry | posthog | segment | mixpanel | amplitude | analytics | telemetry`)
returns nothing. The application has a **user-directed OpenAPI
spec fetch** — `httpx` in `app/services/openapi_service.py`, where the URL is supplied
by the operator (Step 2 "fetch from URL") and gated by the mode-aware fetch policy. It
is categorically not telemetry: no fixed endpoint, no background call. Studio is
otherwise an authoring web server. Engine/KS subprocesses and dependency installs
or generated-app Maven builds have their own network/configuration boundaries;
this claim does not promise offline operation for every workflow. (SSRF characterization of the fetch:
[security-boundary-map.md §3b](security-boundary-map.md#3-attack-surfaces-per-component).)

## 4. Standalone and no runtime coupling

**Studio has no hosted-service dependency.** At runtime it depends on its declared
Python libraries and **local subprocesses it spawns** (the Engine via MCP/CLI, the
Knowledge Server) — there is no call to a hosted MCP or SaaS. In **shared mode** every
Engine invocation is **root-constrained** (`EDGEFORGE_MCP_ALLOWED_ROOTS` +
`EDGEFORGE_SHARED_MODE`, enforced fail-closed by the Engine — MCP and CLI alike), and
each session's KS child is constrained to that session's workspace
(`EDGEFORGE_KS_ALLOWED_ROOTS`). In **local mode** the Engine CLI path runs with the
operator's environment (no root constraint) — local and operator-directed (see
[G8 §3c](security-boundary-map.md#3-attack-surfaces-per-component)).

**Studio authors; the Engine generates.** Studio writes manifest packages the Engine
consumes; it does **not** generate code. The applications it helps produce are
standalone Spring Boot apps with **zero runtime dependency on Studio** — the coupling
is one-way and contract-based (the manifest 2.0 package). Studio and Engine must
be paired at that contract version; generated applications remain independent.

## 5. Data-handling posture

- **[local] Single-user.** Studio runs on the operator's machine; authored content,
  manifest packages, and generated output stay local and are **git-ignored**.
- **[shared] Per-session isolation.** Each principal's session has its own
  server-owned workspace, its own KS database, and ownership-scoped project catalog;
  one session cannot read or write another's state, uploads, KS documents, or output
  (proven by the L2/L4 isolation smoke). Identity uses the seam's **default anonymous
  signed-cookie** session (per-browser): a trusted proxy can authenticate users at the
  edge, but mapping that enterprise user into Studio's principal needs the (deferred)
  proxy/OIDC adapter — so **audit attribution is anonymous-session-level until that
  adapter is wired**, not enterprise-user-level. Structured **audit** records
  project/export/generate/build-run events to a separate SQLite database by default in
  shared mode (local mode remains no-op by default). Startup probes the store and
  refuses service on failure; later write failures do not undo completed mutations and
  surface through a sanitized next-request banner. The local read-only operator CLI
  reports durable database status and exports deterministic CSV; there is no browser
  audit API. Audit retention defaults to 90 days by server insert time and deletes at
  most 5,000 rows per pass.
  Idle sessions are reclaimed by **retention** (path-guarded, with a durable-artifact
  exemption for the regenerate baseline); quotas bound per-session disk / project count
  / KS-DB size.
- **Knowledge Assist OFF by default — no LLM.** With KA off there is no KS UI/state,
  no subprocess spawn, and no live KS call in either posture; KS itself is
  deterministic FTS5/BM25 (no LLM). Optional AI is not enabled here.
- **No PII in the repo.** All fixtures are synthetic; any real/PII data must not be
  committed.
- **At-rest caveat.** Local output, session/catalog, audit, and workspace files are
  cleartext; rely on host filesystem encryption for sensitive content
  ([G8 §5.6](security-boundary-map.md#5-honest-open-items--recommendations)).

## 6. Dependency hygiene

- **Declared surface:** [`requirements.txt`](../requirements.txt) pins the runtime
  and test dependencies (single Python stack — no JavaScript build / npm surface).
- **Reproducible SBOM + license inventory:** regenerated by named, pinned tools via
  `make sbom` / [`scripts/generate-dependency-evidence.sh`](../scripts/generate-dependency-evidence.sh)
  (G4).

## 7. Portability

- **Runtime:** Python **3.11+** plus a small permissive dependency set (§1) — standard
  FastAPI / uvicorn. No proprietary SaaS or vendor runtime is required. A Docker
  Compose dev runtime is also provided.
- **Air-gapped / restricted networks:** use upload/paste instead of URL fetch and
  provide required Python/Maven artifacts through approved offline caches or
  mirrors. Build & Run additionally needs a local JDK/Maven. Optional KS/Engine
  configuration must be evaluated separately; upload/paste alone does not prove
  every downstream workflow is offline.

## 8. Shared-service deployment posture

When run as a **shared authoring service** (`EDGEFORGE_STUDIO_SHARED_MODE=true`):

- **Single replica, design-time only.** Studio remains an **authoring** tool, not a
  production runtime; the per-session workspace filesystem + in-process generation lock
  are replica-bound, so the supported contract is **one replica** (multi-replica HA
  needs externalized lock + session store — deferred; the seam keeps it open).
- **Control ingress with an authenticated TLS gateway and inaccessible direct
  application port.** Current identity and audit attribution remain anonymous
  session-level. Proxy/OIDC adapters are placeholders, not deployed authentication;
  project-supported real identity requires implementation and proof, while the
  operator owns IdP configuration and access policy.
- **Build & Run is server-disabled** by default (`EDGEFORGE_STUDIO_BUILD_RUN_ENABLED`
  false); a production runtime sandbox is a deferred track.
- **RBAC** beyond project ownership is in-org policy (deferred, not foreclosed).

See [deployment-model.md](deployment-model.md) for the full flag matrix and operator
runbook, and [security-boundary-map.md §5](security-boundary-map.md#5-honest-open-items--recommendations)
for the residual open items.

---

## Caveats summary (not buried)

- **Own license unresolved** — project-maintainer decision before publication (§1).
- **License dispositions pending** — dated declared/transitive inventories exist;
  flagged entries and non-Python artifacts need appropriate rights review (§1).
- **[local] No authentication** — single-user, keep on `localhost`
  ([G8 §5](security-boundary-map.md#5-honest-open-items--recommendations)).
- **[shared] Real identity integration remains deferred** — anonymous isolation
  ships; external gateway authentication does not change Studio principals (§8).
- **[shared] Single-replica contract** — multi-replica HA deferred (§8).
- **OpenAPI URL fetch is guarded + mode-aware** — every redirect hop is resolved once,
  address-policy checked, pinned, and peer-verified while preserving Host/SNI/certificate
  checks; ambient proxies are disabled. Responses default to a 5 MiB cap and 10-second
  end-to-end deadline. Exact allowlisting can authorize RFC1918/IPv6-ULA services but
  never metadata or special addresses; shared loopback is forbidden and local loopback
  remains supported. Studio supplies guarded responses through a root-confined,
  fail-closed per-invocation cache while preserving the original `spec_url` manifest
  branch and source-manifest identity, so the child cannot broaden redirect egress or
  change URL-origin ingestion semantics; use upload/paste for air-gap (§3, §7).
- **At-rest local files cleartext** — host-level encryption for sensitive content (§5).
