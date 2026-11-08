# Handoff Security Boundary Map — Studio

> **Import-gate G8.** The trust-boundary / data-flow / attack-surface view a
> **security architect** reads at import — the architecture companion to the G7
> [Compliance & Portability Checklist](compliance-and-portability.md). It maps where
> the trust boundaries are, what data crosses each, where untrusted input enters,
> where the controls sit, and the honest open items.
>
> **Scope:** a *lightweight* now-doc, **not** a full threat model (that defers,
> post-import). Every security claim below was **verified against the actual source**
> (the file/symbol is cited), not asserted.
>
> **Two deployment postures.** Studio now ships **two** modes, and the boundary map
> differs between them:
> - **Local single-user (default, `EDGEFORGE_STUDIO_SHARED_MODE=false`)** — the
>   original posture: one operator, their own machine, no auth, Build & Run on.
> - **Shared multi-session (`EDGEFORGE_STUDIO_SHARED_MODE=true`)** — a shared
>   **authoring** service: per-session isolation, an identity seam, CSRF, server-owned
>   paths, root-constrained Engine/KS on **every** call, audit + ownership, quotas +
>   retention, and Build & Run **server-disabled**. The operator contract for this mode
>   is [deployment-model.md](deployment-model.md).
>
> **Last updated:** 2026-08-20. References the evidence pack as the single source of
> truth — G3 (secret/data scan), G4 (SBOM + licenses) — and does not re-derive it.
> The G10 [handover-evidence index](handover-evidence/README.md) links this doc.

**Publication clarification (2026-10-10):** the shared principal described below
is an anonymous signed-cookie session. Proxy/OIDC adapters currently raise
`IdentityProviderUnavailable`; an authenticating gateway does not map its users
into Studio identity or audit. Real identity integration is pending project
work; the adopter owns gateway/IdP configuration and access policy. The
[deployment contract](deployment-model.md#3-shared-multi-session-authoring-service)
and [publication decision record](publication-preparation.md#remaining-maintainer-decisions)
separate these responsibilities. Dated controls below are not new acceptance proof.

## At a glance

| # | Question a reviewer asks | Short answer | Where |
|---|---|---|---|
| 1 | What is the central boundary? | Studio is a FastAPI **authoring** tool that runs in one of two postures. **Local mode** (default): a single-user, design-time tool whose boundary is the operator's own machine. **Shared mode**: a single-replica shared authoring service whose boundary is the **per-session principal** behind a trusted proxy / SSO. Either way the apps it authors run elsewhere with **zero runtime dependency on Studio**. | [§1](#1-the-central-boundary--two-postures) |
| 2 | Show me the trust boundaries | Two diagrams: local (browser ⇄ localhost ⇄ Studio) and shared (browser ⇄ proxy/SSO ⇄ Studio with **per-principal sessions**, **per-session** server-owned workspace + KS DB, root-constrained ephemeral Engine). | [§2](#2-trust-boundary-diagrams) |
| 3 | Where does untrusted input enter? | **OpenAPI specs** (Step 2 upload/paste/URL), **Knowledge Workspace documents** (`/knowledge/upload`), authoring form input, and — in local mode — operator-supplied **filesystem paths**. In shared mode, paths are **server-owned**, not user-supplied. | [§3](#3-attack-surfaces-per-component) |
| 4 | Where are the controls? | **No `shell=True`** (arg-lists, verified); data-only YAML loaders (PyYAML `safe_load`, plus ruamel round-trip mode for comment-preserving CSV edits); **shared mode** adds an identity seam, CSRF, server-owned per-session paths, **F1 root-constraint on every Engine call** (MCP + CLI), per-session KS DB, a per-output-path generation lock, audit + ownership, quotas + idle-TTL retention, and a server-enforced Build & Run gate; KA OFF by default; no secrets (G3). | [§4](#4-controls--boundaries) |
| 5 | What's still open? | **Project-owned proxy/OIDC identity integration and RBAC support** remain deferred; operators own IdP/gateway configuration and access policy. **Multi-replica HA** (single-replica contract); local-mode operator paths + Build & Run code execution; full threat model deferred. | [§5](#5-honest-open-items--recommendations) |

---

## 1. The central boundary — two postures

Studio is a **design-time authoring tool**, not a runtime service. It runs as a
FastAPI app (`app/main.py`) in one of two postures, selected by
`EDGEFORGE_STUDIO_SHARED_MODE` (the master switch — §6.7 of the
[multi-session architecture design](multi-session-architecture-design.md), and the
operator [deployment-model.md](deployment-model.md)).

Three facts shape the threat model in **both** postures:

- **Studio authors; the Engine generates.** Studio writes manifest packages the
  Engine consumes and orchestrates the Engine / Knowledge Server as **local
  subprocesses**; it does **not** generate code, and the apps it helps produce carry
  **zero runtime dependency** on Studio. Studio's direct execution boundary is
  the developer/build host; a defect affecting authored packages can also affect
  the generated application and must be evaluated along that path.
- **Manifest-contract coupling is one-way.** The only coupling to downstream is the
  reviewed manifest 2.0 package; generated apps are standalone Spring Boot apps.
- **Knowledge Assist is OFF by default.** With KA off there is no KS UI/state, no
  subprocess spawn, and no live KS call — in either posture.

What **differs** by posture:

- **Local single-user (default).** No authentication: the trust boundary is the
  **operator's own machine** — the operator is already trusted to run code locally.
  Subprocess targets (Engine repo, output path) are operator-supplied; the Engine CLI
  path is not root-constrained; Build & Run is available. This is the posture the
  original import-gate docs described, and it is unchanged.
- **Shared multi-session.** A shared **authoring** service (single replica) reached
  through a **trusted proxy / SSO**. The trust boundary moves to the **per-session
  principal**: each session gets its own server-owned workspace, its own KS database,
  and a request-context identity; one session cannot read or write another's state,
  uploads, KS documents, or generated output. Build & Run is **server-disabled**.
  This posture is specified in the multi-session architecture design and proven by the
  L2/L4 smoke harness (two-session isolation + cross-repo fail-closed).

## 2. Trust-boundary diagrams

### 2a. Local single-user (default)

```
  LOCAL DEVELOPER MACHINE  (single user; no production traffic)
  ─────────────────────────────────────────────────────────────────────────
   operator browser
        │  localhost HTTP (no auth — single-user)     ┌─────────────────────┐
        ▼  trust boundary: the local machine          │  Studio (FastAPI)    │
        │  + authoring input / uploaded specs          │  app/main.py         │
        └─────────────────────────────────────────────►│  Jinja2 (autoescape) │
   OpenAPI spec URL ──user-directed fetch──────────────►│                      │
        ▲  egress: guarded http/https fetch             │  writes ─► local     │
        │  scheme/host/network + redirect checks         │   manifest packages  │
   local files / paths (operator-supplied) ────────────►│   + output (ignored) │
                                                        │  spawns (arg-list,   │
                                                        │  no shell) ─► Engine │
                                                        │   MCP/CLI + KS       │
                                                        └─────────────────────┘
```

In local mode the operator is the trust boundary; paths are operator-supplied; the
Engine CLI path and Build & Run are local, operator-directed, and not sandboxed.

### 2b. Shared multi-session authoring service

```
  SHARED AUTHORING SERVICE  (single replica; design-time only — not prod runtime)
  ───────────────────────────────────────────────────────────────────────────────
   user browser ─┐
   user browser ─┤  HTTPS    ┌──────────────────┐  forwarded HTTP + signed cookie
   user browser ─┘──────────►│  Access gateway   │──────────────────────────────┐
                             │  (operator-owned) │   (identity headers ignored) │
                             └──────────────────┘                               ▼
                                                        ┌──────────────────────────────┐
        per-request principal + signed session cookie   │  Studio (FastAPI, 1 replica) │
        CSRF on every unsafe POST (§4)  ───────────────►│  request_context middleware  │
                                                        │  SessionStore (SQLite catalog│
                                                        │   — principal-scoped)        │
        each principal → its OWN:                        │                              │
          • server-owned workspace_root  ───────────────►│  state_dir/workspaces/<sid>/ │
          • KS database (per session)    ───────────────►│   └─ ks/knowledge.sqlite3    │
          • ephemeral Engine per call    ───────────────►│  root-constrained (F1):      │
            (MCP-forced; per-output lock)                │   EDGEFORGE_MCP_ALLOWED_ROOTS│
                                                        │   + EDGEFORGE_SHARED_MODE=1  │
        Build & Run: SERVER-DISABLED (§6.5) ────────────►│  /export/build,/run → 4xx    │
                                                        └──────────────────────────────┘
```

Read it as: each request carries a **principal** — by default an **anonymous, signed
per-browser session** (mapping a proxy/SSO *enterprise user* into the principal needs the
deferred project-owned proxy/OIDC adapter, §5; no such identity path is active
today). Operators configure gateway/IdP access, not Studio's identity adapter.
The SessionStore keys all state by principal; each
session's files, KS DB, and Engine invocations are **server-owned and per-session**;
Engine subprocesses are root-constrained on **every** call; Build & Run is refused.

## 3. Attack surfaces, per component

### 3a. HTTP interface (FastAPI)

`app/main.py` builds a `FastAPI(...)` app with routers + a `/static` mount and **no
`CORSMiddleware`** (same-origin default).

- **Development API surfaces are closed by default.** `/docs`, `/redoc`, and
  `/openapi.json` are disabled unless a local operator explicitly sets
  `EDGEFORGE_STUDIO_ENABLE_API_DOCS=true`. Shared mode refuses startup when that
  opt-in is present; API documentation is never exposed by the shared service.
- **Browser responses carry containment headers.** HTML, JSON, static, redirects,
  and error responses receive `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, and the deliberately
  scoped CSP `frame-ancestors 'none'`. This slice adds no script/style source
  policy, so the existing inline Studio assets continue to work.

- **Local mode:** **no authentication** — the control is the **deployment boundary**
  (keep it bound to `localhost`; do not expose the port).
- **Shared mode:** a request-context middleware (`app/middleware/request_context.py`)
  resolves a **principal** via the identity seam (`app/services/identity.py`), issues a
  **signed session cookie** (HttpOnly/Secure/SameSite), and enforces **CSRF** on every
  unsafe method. The proxy-header / OIDC adapters are deferred project-owned
  placeholders that return HTTP 501 (§5); operators own gateway/IdP configuration
  and access policy. The default adapter mints an anonymous, signed, per-browser
  session and ignores identity headers; it does not reject them as a bypass control.
- **Shared-mode resource controls.** After request context and non-deferred CSRF,
  Studio applies a hybrid contract: one explicit method/path registry covers whole
  costly Engine, KS, upload/inspection, and archive requests, while the named
  request-scoped Class B passthrough-fetch seam covers every guarded URL fetch from
  `/passthrough/describe-spec` and each URL-backed downstream target in
  `/passthrough/save`. Text-only saves remain unthrottled; each remote target fetch
  independently consumes Class B capacity. Each class has a per-principal
  sliding-window rate budget plus principal and process concurrency caps. Full capacity
  returns a bounded `429` with `Retry-After`; it never queues. PR #291 upload-envelope
  failures happen outside this control and consume no capacity. Local mode takes a
  constant-time bypass with no key derivation or in-memory limiter state.

### 3b. Untrusted input — OpenAPI specs + authoring input

- **Upload entry points.** Step 2 ingests OpenAPI specs (`routes/upstream.py`,
  `UploadFile`); project open ingests Studio project JSON at `POST /project/open`
  (`routes/project_file.py`); the Knowledge Workspace ingests documents at
  `POST /knowledge/upload` (`routes/knowledge.py`) only after Studio validates the
  local file type and upload size when KA is enabled. A pure-ASGI policy applies to
  these three POST routes in both local and shared mode before request context or
  multipart parsing: it requires a valid `multipart/form-data` envelope, rejects an
  oversized valid `Content-Length` without reading the body, and counts chunked bodies
  until the same bound is crossed. Early `400`/`413`/`415` responses retain the browser
  containment headers; Step 2 receives its established JSON shape and native form
  routes receive a standalone session-free HTML page.
- **Spec parsing is safe.** Ordinary uploaded, pasted, and URL-fetched specs use
  PyYAML **`yaml.safe_load`**. The downstream CSV visual materializer uses ruamel's
  data-only round-trip loader so comments, key order, and quoting survive structured
  edits; it registers no Python object constructors. There is no unsafe
  object-construction path from author-supplied YAML.
- **OpenAPI URL fetch (guarded SSRF surface).** `openapi_service` uses a guarded fetch
  for **user-supplied** URLs (`openapi_fetch_guard`), mode-aware via
  `EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE`: `disabled` (no fetch); **`allowlist`** (the
  shared-mode default) — only `http`/`https` to **exact operator-approved hosts**
  (`EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS`). Every redirect hop is resolved once;
  all returned addresses are policy-checked, sorted, and carried into address-pinned
  HTTP(S) connections. The original host remains authoritative for HTTP `Host`, TLS SNI,
  and certificate hostname verification, and the connected peer must match an approved
  address. Ambient HTTP(S)/ALL proxy variables are disabled for this fetch path.
  Allowlisting can authorize an exact RFC1918/IPv6-ULA private-service host but never
  bypasses resolution, pinning, peer verification, or the permanent metadata/special-
  address deny rules. Shared mode always rejects loopback; local `open` mode preserves
  localhost/numeric-loopback development, while a loopback alias requires an exact
  allowlist entry. Redirects are manual and bounded to five; bodies are incrementally
  capped at 5 MiB by default (`EDGEFORGE_STUDIO_OPENAPI_FETCH_MAX_BYTES`) with a default
  10-second monotonic deadline (`EDGEFORGE_STUDIO_OPENAPI_FETCH_TIMEOUT_SECONDS`) shared
  by DNS, all address attempts, redirects, and body reads. Before assessment or
  generation, Studio completes this guarded fetch and exposes only the approved response
  through a root-confined, fail-closed per-invocation cache at Engine's normal OpenAPI
  fetch seam. The original manifest and `spec_url` branch remain unchanged, preserving
  URL-origin entity ingestion and the stable `app-definition.yaml` source label, while
  Engine cannot re-fetch, widen redirect egress, or reject Studio-approved local loopback.
  Studio still overrides ambient Engine allowlist values with its normalized list as
  defense in depth. No credentials are attached in any mode.
- **Upload size and declared type.** `EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES` remains the
  per-file cap (default **50 MiB**) and `read_upload_limited()` retains its bounded
  reader as defense in depth. The complete multipart request cap is the configured
  file cap plus a fixed **1 MiB** envelope allowance (default **51 MiB**) for form
  boundaries and non-file fields. A chunked request can begin parsing before it crosses
  the cap, but no further content reaches the application and parser cleanup runs. The
  three routes also allowlist filename extensions and declared file-part content types;
  `application/octet-stream` remains accepted for browser/test-client fallbacks. Those
  MIME values are client assertions, not content proof: the existing OpenAPI, project,
  and Knowledge parsers remain authoritative. In shared mode, per-session disk and
  KS-DB quotas apply on top (§4, §6.7).

### 3c. Subprocess orchestration (Engine / KS / Build & Run)

Studio spawns the Engine (MCP or CLI) and the Knowledge Server as local subprocesses.

- **No shell injection (verified).** `appbuilder_integration._run_subprocess` calls
  `subprocess.run(cmd, ...)` with an **argument list** and **no `shell=True`** (a `grep`
  for `shell=True` across `app/` returns nothing).
- **Engine diagnostics are projected before crossing a trust boundary.** Raw child
  stdout/stderr and command metadata remain internal for parsing and control flow.
  Browser validation/generation/assessment responses, persisted
  `assessment-report.json`, regeneration preview/apply output, and default Studio
  Engine logs receive only a bounded sanitized message plus an opaque diagnostic ID.
  The projection removes traceback frames, absolute paths, command arguments,
  credential-like values, secret-bearing URL components, and control characters
  while retaining actionable schema/field failures. The ID contains no user data
  and is not a retrieval token.
- **F1 — every Engine call is root-constrained in shared mode.** `app/services/`…
  `appbuilder_integration._engine_subprocess_env` sets **`EDGEFORGE_MCP_ALLOWED_ROOTS`**
  (the per-session server-owned root) **and `EDGEFORGE_SHARED_MODE=1`** on **every**
  Engine invocation — validate, assess, generate, regen plan and apply. Generate is **MCP-forced** in
  shared mode (the env-less CLI fallback is disabled). The Engine enforces these
  fail-closed (`appbuilder/core/path_safety.py`): a manifest/output path resolving
  **outside** the allowed root — including `..` traversal and symlink escapes — is
  rejected, and the Engine install tree / cwd are **never** implicit roots. This is the
  two-sided fix (Studio passes the root; the Engine refuses out-of-root), proven by the
  L4 fail-closed smoke. The dated [actual caller adversarial proof](handover-evidence/studio-adversarial-handoff.md)
  additionally tests signed-cookie requests, hostile restored paths and inherited
  environment. Concrete file/output/KS targets are confined before access, and
  shared `preflight_engine_package` rejects package symlinks before child invocation
  in export and regen plan/apply (both exported-manifest parent and managed-package
  trees), including direct Studio adapter entrypoints. Regen checks precede status
  hashing and are repeated before the child. Regen CLI is intentional, not a
  shared generation fallback; regen remains disabled by default.
  **Entrypoint root checks are not an OS sandbox or universal nested-input guard:**
  the frozen Engine followed a local-spec symlink without that Studio preflight.
  Static preflight does not protect against concurrent host filesystem mutation.
- **KS children are root-constrained per session.** Each session's KS subprocess gets
  `EDGEFORGE_KS_ALLOWED_ROOTS` scoped to that session's `workspace_root/ks`
  (`ks_integration` / `ks_workspace`), so a KS child can only read its own session's
  workspace.
- **Local mode is unchanged.** With `EDGEFORGE_STUDIO_SHARED_MODE=false`,
  `_engine_subprocess_env` strips those vars and the Engine CLI stays unconstrained for
  dev convenience (the Engine treats unset roots as unconstrained **only** when
  `EDGEFORGE_SHARED_MODE` is not set). Subprocess targets remain operator-supplied — not
  a privilege boundary for a single-user local tool (§5).
- **Residual local Build & Run output is separate.** Step 8 generated-app Maven,
  runtime output, and log tails are local-runtime surfaces and are not sanitized by
  the Engine-diagnostic projection in this change. Build & Run remains server-disabled
  in shared mode; further local-runtime log containment is a separate follow-up.

### 3d. Sessions, paths, and isolation (shared mode)

- **Server-owned paths.** In shared mode, output and export paths are derived
  server-side from the session's `workspace_root` (`app/services/path_resolver.py`);
  a user-supplied `output_path` is **ignored**. Per-session `workspace_root` lives under
  `state_dir/workspaces/<session_id>` (`app/services/sqlite_session_store.py`).
- **Principal-scoped catalog + ownership.** The SQLite SessionStore keys sessions and
  projects by `principal_id`; cross-principal project access is rejected
  (`save_project` / `get_project` / `delete_project` enforce ownership). Connections use
  WAL + a process lock + `foreign_keys=ON` (projects cascade on session delete).
- **Per-output generation lock.** `app/services/generation_locks.acquire_generation_lock`
  serializes concurrent generates to the same output path (non-blocking; a same-path
  double-submit gets "already in progress").
- **Lifecycle + retention.** `app/services/ks_lifecycle` reaps idle KS subprocesses and
  caps concurrency; `app/services/retention` purges idle/expired session workspaces with
  a **path-safety guard** (only under `state_dir/workspaces/`) and a **durable-artifact
  exemption** (the regen baseline survives idle-TTL). Quotas (`app/services/quotas`)
  reject over-limit actions rather than deleting data.

### 3e. Template rendering + static

The wizard UI renders authored content through **Jinja2** with default autoescaping
(on for `.html`; no override found). `/static` serves bundled assets only.

### 3f. Audit (shared mode)

`app/services/audit` emits structured events (principal + session IDs) for project
open/save, export, generate, and **build-run attempts including the disabled-on-shared
rejection**. Shared mode persists those events by default to the separate
`state_dir/studio-audit.sqlite3` database; local mode remains no-op by default. An
operator may select `noop` or `sqlite`, override the database with an absolute
operator-owned path, and set retention (90 days by default). SQLite startup applies
WAL and the locked schema, performs a transactional write/delete probe, and runs one
bounded retention pass. A failure refuses startup. Runtime writes use short-lived
audit-only connections and a two-second busy timeout, so a completed mutation may be
delayed by at most that bound but is never rolled back or changed by a later audit
failure.

Runtime failures are reduced to a closed error kind, rate-limited in default logs, and
tracked in a process-local health snapshot. In shared mode an accessible banner first
appears on the request after the failure and clears after a successful later write; it
contains no path, SQL, exception, or event detail. Durable status and deterministic CSV
retrieval are local operator actions through `python -m app.tools.audit_export`; the CLI
uses read-only database access and does not claim access to process-local health. There
is no browser audit or health API. Retention uses server insert time (`recorded_at`),
runs at most hourly after successful writes, and deletes at most 5,000 rows per pass.

**Attribution level:** the principal is the **anonymous
signed-cookie session** by default, so audit today is **session-level**, not
enterprise-user-level; it becomes user-level only once the proxy/OIDC identity adapter
is wired (§5).

## 4. Controls + boundaries

| Control | Where (verified) | Local | Shared |
|---|---|---|---|
| **No shell injection** | `_run_subprocess` — arg-list, no `shell=True` | ✓ | ✓ |
| **Safe YAML parsing** | PyYAML `safe_load`; data-only ruamel round-trip mode for CSV materialization | ✓ | ✓ |
| **Identity seam + signed session cookie** | `identity.py`, `request_context.py` | n/a (no auth) | ✓ |
| **CSRF on unsafe methods** | `csrf.py` (session-scoped token), middleware → 403 | n/a | ✓ |
| **Server-owned per-session paths** | `path_resolver.py`, `sqlite_session_store.py` | n/a | ✓ |
| **Every Engine call root-constrained (F1)** | `_engine_subprocess_env` (`EDGEFORGE_MCP_ALLOWED_ROOTS` + `EDGEFORGE_SHARED_MODE`); Engine `core/path_safety.py` fail-closed | MCP only | **MCP + CLI** |
| **Per-session KS DB + root-constraint** | `ks_workspace.py`, `EDGEFORGE_KS_ALLOWED_ROOTS` | per-project | **per-session** |
| **Per-output generation lock** | `generation_locks.py` | ✓ | ✓ |
| **Bounded request resource controls** | `request_resource_limits.py`, in-memory fixed route registry plus named request-scoped passthrough Class B fetch seam | bypass | **per-principal rate + principal/process concurrency** |
| **Principal-scoped catalog + ownership** | `sqlite_session_store.py` | n/a | ✓ |
| **Quotas + idle-TTL retention (path-guarded)** | `quotas.py`, `retention.py`, `ks_lifecycle.py` | n/a | ✓ |
| **Build & Run server-enforced gate** | `EDGEFORGE_STUDIO_BUILD_RUN_ENABLED` (routes refuse when off) | on | **off (4xx)** |
| **Durable structured audit** | `audit.py`, separate SQLite database + local read-only CLI | no-op default | **SQLite default** |
| **No cross-origin exposure** | `app/main.py` — no `CORSMiddleware` | ✓ | ✓ |
| **HTML autoescaping** | Jinja2 default | ✓ | ✓ |
| **Subprocess timeouts** | `_run_subprocess(timeout=...)` (env-tunable) | ✓ | ✓ |
| **KA OFF by default** | no KS calls / state leakage with KA off | ✓ | ✓ |
| **No secrets in repo** | gitleaks CI on every PR/push (G3) | ✓ | ✓ |

## 5. Honest open items / recommendations

Nothing security-relevant is hidden. Items marked closed are documented as current
state; remaining fixes belong in their own changes.

| # | Item | Surface | Posture / recommendation |
|---|---|---|---|
| 1 | **SSO / OIDC / proxy-header integration** | identity seam | Shared mode ships the **seam** (`EDGEFORGE_STUDIO_AUTH_MODE`, signed-cookie default); **project-owned proxy/OIDC integration is deferred** and selecting either placeholder returns HTTP 501. Operators must restrict ingress through an authenticated TLS gateway and keep the Studio port inaccessible to untrusted clients. **Identity headers are ignored today, not rejected as a bypass control.** A future trusted-header integration must require the proxy to strip client-supplied identity headers. Operators own gateway/IdP configuration and access policy. **The principal and audit attribution remain anonymous-session-level, not enterprise-user-level.** |
| 2 | **RBAC / authorization policy** | Studio | Project **ownership** isolation ships; project-supported role/permission integration remains deferred. Operators own their access policy; that does not supply the missing Studio integration. |
| 3 | **Multi-replica HA** | deployment | Shared mode is a **single-replica** contract (the workspace filesystem + in-process generation lock are replica-bound). Running >1 replica needs sticky sessions or a shared workspace volume + externalized lock/session store — the `SessionStore` seam keeps that path open (§4.2 of the design). |
| 4 | **Local-mode operator paths + Build & Run** | `appbuilder_integration` | In **local** mode the Engine CLI path and Build & Run run with the operator's environment and operator-supplied targets — no-shell but **not sandboxed**. Acceptable for a single-user local tool. In **shared** mode this surface is closed: paths are server-owned, every Engine call is root-constrained, and Build & Run is **disabled**. |
| 5 | **Local Build & Run code execution** | Build & Run (Step 8) | Local mode can build/run a generated app at operator direction (non-prod). Shared mode refuses it server-side; a production runtime sandbox (containers / off-host runner) is a deferred track. |
| 6 | **At-rest local files are cleartext** | output / session / audit / catalog | Manifest packages, generated output, the SQLite session and audit databases, and per-session workspaces are unencrypted on disk; rely on **host filesystem encryption** for sensitive content. |
| 7 | **Full threat model** | All | This is a lightweight now-doc; a full threat model defers post-import. |
| 8 | **Anonymous and in-memory request limits** | shared-mode resource controls | Per-principal limits provide fairness and accidental-overload protection, not durable anti-abuse identity: discarding the signed anonymous cookie creates a new principal and resets its history. Process-wide caps are the hard per-process protection until real identity/RBAC ships. State resets on restart and is single-replica only; multi-replica enforcement needs an external design. |

---

## Caveats summary (not buried)

- **Two postures** — local single-user (no auth, by design; keep on `localhost`) vs
  shared multi-session (identity seam + per-session isolation). Pick deliberately via
  `EDGEFORGE_STUDIO_SHARED_MODE` ([deployment-model.md](deployment-model.md)).
- **Shared-mode real identity integration is project-owned and deferred** — the
  signed-cookie seam supplies anonymous sessions. Operators own gateway/IdP
  configuration and access policy; injecting identity headers has no effect today.
  **Audit attribution stays session-level, not enterprise-user-level** (§5.1).
- **Single-replica contract** — multi-replica HA needs externalized lock + session
  store (§5.3).
- **F1: every Engine call is root-constrained in shared mode** — Studio passes the
  per-session root; the Engine refuses out-of-root (`..`/symlink/Engine-tree)
  fail-closed (§3c).
- **OpenAPI URL fetch is guarded + mode-aware** — every hop is resolved once, policy-
  checked, address-pinned, peer-verified, proxy-free, redirect-bounded, response-bounded,
  and covered by one end-to-end deadline. Exact allowlisting can authorize private
  services but not metadata/special targets; shared loopback remains forbidden and local
  loopback remains supported. Assess/generate children receive guarded responses through
  a root-confined cache while retaining normal `spec_url` semantics; use upload/paste for
  air-gap (§3b).
- **Build & Run executes code locally** — local-only, at operator direction; disabled
  in shared mode (§5.5).
- **At-rest files cleartext** — host encryption for sensitive content (§5.6).
- **No full threat model yet** — deferred post-import (§5.7).

## See also

- [Consolidated image disposition](handover-evidence/studio-image-consolidated-disposition.md) —
  dated AMD64 runtime/tooling coverage and open decisions; not risk acceptance,
  M2 clearance, or new Studio-to-Engine caller-handoff proof.
- [Deployment model](deployment-model.md) — the operator contract for local vs shared
  mode (flag matrix, single-replica, identity/proxy seam, Build & Run off).
- [Compliance & Portability Checklist](compliance-and-portability.md) (G7) — the
  compliance companion to this architecture map.
- [Multi-session architecture design](multi-session-architecture-design.md) — the
  shared-mode model (SessionStore, per-session isolation, §6.7 flag matrix).
- [Handover-evidence index](handover-evidence/README.md) (G10) — concern → evidence.
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — the authoritative invariants
  (paired manifest 2.0 contract, KA-OFF default, local-single-user default).
