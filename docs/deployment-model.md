# Deployment Model — Studio

> **Operator contract.** How to run EdgeForge **Studio** in each of its two postures,
> what each flag does, and what is in/out of scope. The security architecture behind
> this is [security-boundary-map.md](security-boundary-map.md) (G8); the compliance
> answers are [compliance-and-portability.md](compliance-and-portability.md) (G7); the
> full design is [multi-session-architecture-design.md](multi-session-architecture-design.md).
>
> **Publication guidance checked:** 2026-10-10 at Studio `a22b95b`; this prose
> clarification does not repeat the historical runtime campaigns.

## 1. Two postures

| | **Local single-user** (default) | **Shared multi-session** |
|---|---|---|
| Switch | `EDGEFORGE_STUDIO_SHARED_MODE=false` (default) | `EDGEFORGE_STUDIO_SHARED_MODE=true` |
| Who | One operator, their own machine | Many users, one shared **authoring** service |
| Trust boundary | The operator's machine | Anonymous per-session principal; operator-controlled ingress |
| Auth | None (by design) | Anonymous signed-cookie identity; proxy/OIDC adapters deferred |
| Paths | Operator-supplied | **Server-owned**, per session |
| Engine calls | MCP root-constrained; CLI unconstrained (dev) | **Every** call root-constrained, fail-closed (F1) |
| KS database | Per project | **Per session** |
| Build & Run | On | **Server-disabled** |
| Replicas | 1 (your machine) | **1** (single-replica contract) |

Both postures are **design-time authoring** tools. The apps Studio helps author run
elsewhere with **zero runtime dependency on Studio**. Studio never generates code — the
Engine does (the only coupling is the reviewed manifest 2.0 package). Studio and
Engine must therefore be deployed as a compatible pair for manifest 2.0.

## 2. Local single-user (default)

The original posture, unchanged. Run it on your own machine:

```
uvicorn app.main:app            # binds localhost by default
# or the provided Docker Compose dev runtime
```

- **No authentication** — the control is the deployment boundary. **Keep it bound to
  `localhost`; do not expose the port.**
- FastAPI's `/docs`, `/redoc`, and `/openapi.json` surfaces are disabled by default.
  A local operator may enable all three with
  `EDGEFORGE_STUDIO_ENABLE_API_DOCS=true`; do not expose that development opt-in on
  a network-facing deployment.
- Build & Run is available; subprocess targets (Engine repo, output path) are
  operator-supplied; the Engine CLI path is not sandboxed — acceptable for a
  single-user local tool (see [G8 §5](security-boundary-map.md#5-honest-open-items--recommendations)).
- None of the shared-mode secure defaults apply.

## 3. Shared multi-session authoring service

A single-replica shared authoring service. Minimum operator checklist:

1. **Set the master switch:** `EDGEFORGE_STUDIO_SHARED_MODE=true`.
2. **Restrict ingress through an operator-controlled authenticated TLS gateway**;
   keep the Studio application port inaccessible to untrusted clients. Current
   Studio identity remains `anonymous`, even when the gateway authenticates a
   user. Do not select `proxy` or `oidc` expecting a working identity integration:
   both are placeholders that refuse identity resolution. Mapping real users
   into Studio principals/audit requires the deferred adapter and separate proof.
   A future trusted-header integration must strip client-supplied identity headers.
3. **Set a strong `EDGEFORGE_STUDIO_SESSION_SECRET`** (signs session cookies; rotate
   per your policy).
4. **Serve over HTTPS** (the proxy terminates TLS; secure-cookie posture assumes it).
5. **Provision a writable `EDGEFORGE_STUDIO_STATE_DIR`** — it holds the separate SQLite
   session/project and audit databases plus per-session `workspaces/<session_id>/`
   trees. Back it up per your policy; use host-filesystem encryption for sensitive
   content.
6. **Point at the operator-configured Engine repo** (`EDGEFORGE_STUDIO_ENGINE_REPO`);
   per-session paths and roots are derived server-side — user values are ignored.
7. **Leave Build & Run off** (`EDGEFORGE_STUDIO_BUILD_RUN_ENABLED=false`, the default).
8. **Run a single replica** (see §5).

Shared mode refuses startup if API documentation is explicitly enabled. All normal
responses also deny framing, disable MIME sniffing, and suppress referrer disclosure;
the scoped CSP contains only `frame-ancestors 'none'` and does not constrain the
existing inline script/style assets.

What the service enforces for you in this mode: per-session server-owned workspaces, a
per-session KS database, root-constrained Engine invocations on every call (F1),
per-output generation locking, CSRF on unsafe POSTs, principal-scoped project ownership,
structured audit, quotas, and idle-session retention.

Shared mode starts with durable SQLite audit enabled. Startup creates the audit parent,
applies the schema and WAL mode, verifies a transactional probe, and runs one bounded
retention pass; any failure refuses service. Runtime audit writes remain best-effort
after completed mutations and may wait up to the configured two-second SQLite busy
timeout. A persistence failure is shown as a sanitized banner beginning with the next
request and clears after a later successful write. Operators inspect durable status or
export deterministic CSV locally with `python -m app.tools.audit_export`; Studio exposes
no browser audit or health endpoint. Attribution remains anonymous-session-level until
the proxy/OIDC identity adapter is wired.

## 4. Configuration — flag matrix

Defaults shown are for `EDGEFORGE_STUDIO_SHARED_MODE=true`. When shared mode is
**false**, none of the secure defaults apply and Studio behaves as the local
single-user tool (Build & Run included).

| Flag | Values | Default (shared) | Effect |
|---|---|---|---|
| `EDGEFORGE_STUDIO_SHARED_MODE` | bool | `false` | Master switch; when true the secure defaults below apply. |
| `EDGEFORGE_STUDIO_AUTH_MODE` | `anonymous` \| `proxy` \| `oidc` | `anonymous` | Only anonymous signed-session identity is implemented; proxy/OIDC select deferred placeholders, not authentication. |
| `EDGEFORGE_STUDIO_SESSION_SECRET` | string | (required) | Signs session cookies; set a strong value and rotate per policy. |
| `EDGEFORGE_STUDIO_STATE_DIR` | path | (operator) | Holds the SQLite catalog + per-session `workspaces/`. |
| `EDGEFORGE_STUDIO_ENGINE_REPO` | path | (operator) | Engine checkout invoked per session (server-owned; user values ignored). |
| `EDGEFORGE_STUDIO_BUILD_RUN_ENABLED` | bool | `false` | Server-enforced Build & Run gate (routes refuse when off). |
| `EDGEFORGE_STUDIO_ENABLE_API_DOCS` | bool | `false` | Enables `/docs`, `/redoc`, and `/openapi.json` together for local development only. Shared mode plus this opt-in is a startup error. |
| `EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE` | `disabled` \| `allowlist` \| `open` | `allowlist` | URL-fetch policy. `allowlist` requires an exact normalized host from `EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS`; it may authorize RFC1918/IPv6-ULA services but never skips resolution, address pinning, peer verification, redirect revalidation, or permanent metadata/special-address refusal. Shared loopback is always rejected. Local `open` permits public targets plus localhost/numeric loopback; private services and loopback aliases require an exact allowlist entry. `disabled` forbids fetch and Studio-triggered assess/generate. Studio fetches reviewed URLs itself and binds the responses into Engine's normal URL fetch seam through a root-confined, fail-closed per-invocation cache. The original manifest and `spec_url` remain unchanged, preserving URL-origin ingestion semantics and deterministic source labels while preventing child-policy drift. The normalized allowlist still overrides ambient Engine values as defense in depth. |
| `EDGEFORGE_STUDIO_OPENAPI_FETCH_MAX_BYTES` | positive integer bytes | `5242880` (5 MiB) | Maximum URL-fetched OpenAPI response body. Valid oversized `Content-Length` is rejected before reading; unknown/chunked bodies stop at the first bounded overflow. |
| `EDGEFORGE_STUDIO_OPENAPI_FETCH_TIMEOUT_SECONDS` | positive integer seconds | `10` | One monotonic end-to-end deadline shared by DNS resolution, all address attempts, redirect hops, and incremental body reads. Invalid/non-positive values fall back to 10. |
| `EDGEFORGE_STUDIO_AUDIT_SINK` | `noop` \| `sqlite` | `sqlite` | Durable audit sink. The local-mode default is `noop`; invalid explicit values fail startup. |
| `EDGEFORGE_STUDIO_AUDIT_DB_PATH` | absolute path | `<state_dir>/studio-audit.sqlite3` | Optional operator-owned audit database path. Relative paths are rejected; an absolute override may live outside the state directory. |
| `EDGEFORGE_STUDIO_AUDIT_RETENTION_DAYS` | integer >= 1 | `90` | Retention based on server insert time (`recorded_at`), with at most 5,000 deletions per pass. |
| `EDGEFORGE_STUDIO_MAX_UPLOAD_BYTES` | integer bytes | `52428800` (50 MiB) | Per-file cap for Step 2 OpenAPI, project JSON, and Knowledge Workspace uploads. Each protected multipart request is separately capped at this value plus a fixed 1 MiB envelope allowance (51 MiB by default); valid `Content-Length` is rejected before body parsing and chunked requests stop at the same total. Extension and file-part MIME allowlists apply in both modes, but MIME is client-declared metadata and existing parsers remain authoritative. |
| `EDGEFORGE_STUDIO_MAX_SESSION_DISK_BYTES` | integer bytes | `5368709120` | Per-session workspace quota; over-limit actions rejected, not deleted. |
| `EDGEFORGE_STUDIO_MAX_PROJECTS_PER_PRINCIPAL` | integer count | `100` | Principal-scoped project catalog cap. |
| `EDGEFORGE_STUDIO_MAX_KS_DB_BYTES` | integer bytes | `1073741824` | Per-session Knowledge Workspace DB size cap. |
| `EDGEFORGE_STUDIO_MAX_KS_SUBPROCESSES` | integer count | `8` | Process-wide cap for Studio-managed KS subprocesses. |
| `EDGEFORGE_STUDIO_KS_IDLE_TTL_SECONDS` | integer seconds | `1800` | Idle TTL before Studio reaps a managed KS subprocess. |
| `EDGEFORGE_STUDIO_SESSION_IDLE_TTL_SECONDS` | integer seconds | `86400` | Idle TTL before Studio purges expired session rows + volatile workspace contents (durable regen baseline exempt). |
| `EDGEFORGE_STUDIO_ENGINE_VALIDATE_TIMEOUT_SECONDS` | integer seconds | `15` | Manifest validation subprocess timeout. |
| `EDGEFORGE_STUDIO_ENGINE_ASSESS_TIMEOUT_SECONDS` | integer seconds | `30` | Engine assess subprocess timeout. |
| `EDGEFORGE_STUDIO_ENGINE_GENERATE_TIMEOUT_SECONDS` | integer seconds | `120` | Engine generate timeout. |
| `EDGEFORGE_STUDIO_BUILD_TIMEOUT_SECONDS` | integer seconds | `600` | Local generated-app build timeout (local mode). |
| `EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED` | bool | `false` | **v4.1.0 fast-follow.** Enables the regen-preview *maintain* flow (§15): a durable managed baseline is captured at generate, and the operator can preview the Engine **Change Plan** (adds / field changes / edge-contract impact + additive-migration preview) and **approve → apply** additive changes (destructive + drift fail closed). OFF (default) → the regen route 404s and no baseline is captured (identical to v4.0.0). Needs an Engine at the regenerate-maintain version (emits `db/schema-baseline.json`) for DB-delta previews; otherwise the preview is manifest-only. |

### 4a. Shared-mode request resource controls

Studio always installs the limiter because the app is module-level, but it performs a
constant-time bypass in local mode: it does not classify routes, derive a principal, or
allocate/mutate limiter state. Shared mode applies the following four settings to each
fixed class `A`, `B`, `C`, `C2`, and `D`:

```text
EDGEFORGE_STUDIO_RATE_<CLASS>_MAX
EDGEFORGE_STUDIO_RATE_<CLASS>_WINDOW_S
EDGEFORGE_STUDIO_RATE_<CLASS>_CONCURRENCY_PRINCIPAL
EDGEFORGE_STUDIO_RATE_<CLASS>_CONCURRENCY_PROCESS
```

| Class | Protected work | Default rate | Principal / process concurrency |
|---|---|---:|---:|
| A | Engine, package write, Build & Run, regeneration | 6 / 300 seconds | 1 / 2 |
| B | Guarded outbound OpenAPI fetch: registry-controlled Step 2 URL ingest plus the request-scoped passthrough fetch seam | 20 / 300 seconds | 2 / 6 |
| C | KS review and mutation | 30 / 300 seconds | 2 / 6 |
| C2 | KS drawer and read surfaces | 120 / 300 seconds | 4 / 12 |
| D | Upload, parse, inspection, archive generation | 60 / 300 seconds | 4 / 12 |

Explicit values must be non-negative integers. `MAX=0` or `WINDOW_S=0` disables only
rate tracking; either concurrency value of `0` disables only that counter. Remaining
dimensions stay active. Whole-request enforcement uses an exact route registry; the
named request-scoped passthrough Class B fetch seam independently acquires capacity for
`/passthrough/describe-spec` URL mode and once for each URL-backed downstream target in
`/passthrough/save`. It therefore protects remote work without throttling text-only
saves. Full capacity immediately returns `429` plus `Retry-After` and never queues.
`/export/stop`, `/export/reset`, `/export/run-status`, artifact reads, normal page
renders, and text-only ordinary saves remain unthrottled. The in-memory principal table
is capped at 10,000 idle/LRU-evicted entries; active requests are never evicted.

These controls are process-local and apply only to one shared-mode replica. Anonymous
signed-cookie principals provide fairness and accidental-overload protection, not durable
anti-abuse identity: clearing the cookie creates a new principal and rate history.
Process-wide counters are therefore the hard per-process protection until real
identity/RBAC and any multi-replica design exist. Existing upload bounds, KS subprocess
caps, Engine timeouts, quotas, and generation locks remain complementary.

### 4b. Cross-repo contract — Engine root-constraint (F1)

In shared mode Studio propagates two **Engine-side** environment variables on **every**
Engine invocation (validate / assess / generate); do not set these yourself — Studio
manages them per call, and they must never be set on Studio's own process:

| Variable | Who sets it | Meaning |
|---|---|---|
| `EDGEFORGE_MCP_ALLOWED_ROOTS` | Studio (per call) | The per-session server-owned root the Engine may read/write. |
| `EDGEFORGE_SHARED_MODE` | Studio (per call) | `1` in shared mode; makes the Engine **fail closed** if roots are unset. |

The Engine enforces these fail-closed (`appbuilder/core/path_safety.py`): any
manifest/output path resolving outside the allowed root — including `..` traversal and
symlink escapes — is rejected, and the Engine install tree / cwd are never implicit
roots. Generate is **MCP-forced** in shared mode (no env-less CLI fallback). This is the
two-sided cross-session isolation proof (F1), covered by the L4 fail-closed smoke.

## 5. Single-replica contract

Shared mode is supported as a **single replica**. The per-session workspace filesystem
and the in-process generation lock are replica-bound, so running more than one replica
would break isolation/locking guarantees. Multi-replica HA needs **both** an
externalized session store **and** sticky sessions or a shared workspace volume +
externalized lock — the `SessionStore` seam keeps that path open, but it is **not built
here** (§4.2 of the design).

## 6. Deferred work and operator responsibilities (not in this release)

- **Project-owned proxy/OIDC identity integration** — the identity **seam** ships;
  the adapters are deferred placeholders returning HTTP 501. Operators own
  authenticated gateway/IdP configuration and access policy, not the missing
  Studio integration. Identity headers are ignored today; Studio's principal
  and **audit attribution** remain the **anonymous signed-cookie session**, not
  the enterprise user. Future trusted-header integration must require stripping
  client-supplied identity headers at the proxy.
- **RBAC / authorization support** — project-supported integration beyond project
  ownership remains deferred; operators own their role/access policy.
- **Multi-replica HA** — single-replica contract (§5).
- **Production Build & Run sandbox** — containers / off-host runner; deferred track.
- **Generated-app Build & Run diagnostic containment** — Step 8 Maven/runtime output
  and log tails remain a separate local-runtime surface. The centralized Engine
  diagnostic projection covers validate, assess, generate, and regeneration
  preview/apply, but does not claim to sanitize these Build & Run logs. Shared mode
  continues to refuse Build & Run server-side.
- **Safe rename / deleted developer-file reconciliation in regen-preview** — the
  v4.1.0 maintain flow renders and applies the Engine Change Plan for additive
  changes; rename-as-destructive and deleted developer-file policy remain Engine/suite
  contract follow-ups.

## See also

- [security-boundary-map.md](security-boundary-map.md) (G8) — trust boundaries + controls.
- [compliance-and-portability.md](compliance-and-portability.md) (G7) — compliance answers.
- [multi-session-architecture-design.md](multi-session-architecture-design.md) — the
  full design (SessionStore, per-session isolation, §6.7 flag matrix, §15 regen track).
- [`CONTRIBUTING.md`](../CONTRIBUTING.md) — authoritative invariants.
