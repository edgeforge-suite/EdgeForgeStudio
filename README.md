# EdgeForge Studio

> **Current implementation (5.0.0 source baseline):** Studio is the human-facing FastAPI
> companion app for the EdgeForge suite. The current baseline includes CRUD,
> passthrough-router, Kafka integration, file/XML/SOAP edge-contract authoring,
> Evidence Trail metadata, shared-mode session isolation, root-constrained Engine
> invocation, Studio L2/L4/L5 smoke harness entries, and the feature-flagged
> regen-preview maintain flow.

**Generate reviewed EdgeForge manifest packages without hand-authoring the manifest.**

EdgeForge Studio helps an author capture intent, ingest upstream contracts,
review Knowledge Assist suggestions, export a valid EdgeForge package, and invoke
the EdgeForge Engine for validation/generation. Studio does **not** generate code
itself; the Engine owns generation.

> **Accessibility known limitation:** A11y-01 remains open. In one native Safari/VoiceOver
> desktop observation, a successful Step 5 save completed visually but its outcome was not spoken;
> three required cases remain untested. Structural accessibility checks remain mandatory, and no
> claim of complete or verified accessibility is made. To reproduce, use native Safari with VoiceOver
> and its Caption Panel in the desktop Step 5 downstream editor, then save a valid interface. The
> save may succeed without a spoken outcome. [Studio issue #302](https://github.com/santosh-sh/EdgeForgeStudio/issues/302)
> records the limitation. The pre-v5 issue and PR links refer to the private development archive,
> accessible only to authorized readers. See the [native observation record](docs/studio-ux-refresh/pr24a-a11y-walkthrough.md#a11y-01-v5-deferral-evidence).
> The coordinated policy merged in [Studio PR #299](https://github.com/santosh-sh/EdgeForgeStudio/pull/299)
> and [Engine/Suite PR #313](https://github.com/santosh-sh/EdgeForge/pull/313) makes A11y-01 alone
> non-blocking for publication, tags, releases, and promoted demos. An authorized release or demo
> must carry an audience-accessible notice of its impact and reproduction. All four native cases
> remain required for closeout; other acceptance gates remain binding.

Studio source is licensed under [Apache-2.0](LICENSE), copyright Santosh Hommaradi;
see [NOTICE](NOTICE) and the DCO 1.1 contribution guidance. The source repository is
[edgeforge-suite/EdgeForgeStudio](https://github.com/edgeforge-suite/EdgeForgeStudio).
Source-and-tags publication requires the recorded publication checks, including
maintainer publication authorization and verified reporting routes.
See [publication preparation](docs/publication-preparation.md) for the release requirements,
[CONTRIBUTING.md](CONTRIBUTING.md) for contribution/review guidance, and
[SECURITY.md](SECURITY.md) before reporting a suspected vulnerability.

The existing `santosh-sh` repository, pre-v5 PR/issue links and dated evidence are
private historical references, not public contribution or security-reporting
channels. They remain unchanged for traceability; the new source destination does
not promise public access to that history or to private raw proof artifacts.

## Project intent and community

EdgeForge is an independently maintained open-source project, shared freely under
[Apache-2.0](LICENSE). Contributions and feedback are welcome. Individuals and
enterprises may use, modify and redistribute it, including commercially, under
those terms. The maintainer does not seek sponsorship or offer paid services,
consulting, custom implementation or managed deployments through this project.
No response deadlines, fixes, delivery dates or ongoing operational support are
promised. Community contributions that improve correctness, stability and
usability are especially welcome. Enterprise adoption is welcome under the
same license; it does not establish affiliation, endorsement or maintainer
service commitments.

Start with the [documentation](docs/README.md). Use
[project issues](https://github.com/edgeforge-suite/EdgeForgeStudio/issues) for
ordinary questions, bugs and suggestions. See [CONTRIBUTING](CONTRIBUTING.md) for
contributions and [SECURITY](SECURITY.md) for private vulnerability reporting.
Share only synthetic examples and redacted diagnostics.

## Baseline Tags

These milestones belong to the private pre-v5 development archive; their tags
were not imported into this repository. The selected v5 successor sources,
execution and justified reuse are recorded in the
[November 14 results](https://github.com/edgeforge-suite/EdgeForge/blob/e33869e6ba595e280a4631dbf11e451fb33fe2a6/docs/handover-evidence/v5-dependency-acceptance-2026-11-14.md).
Later independent approval is recorded separately. The
[November 10 results](https://github.com/edgeforge-suite/EdgeForge/blob/92d0de224d127525b3b3db1365cf931188ccfffb/docs/handover-evidence/v5-acceptance-2026-11-10.md)
retain the preceding selection's scope. Use the exact successor sources named in
the November 14 results and [pairing guide](https://github.com/edgeforge-suite/EdgeForge/blob/e33869e6ba595e280a4631dbf11e451fb33fe2a6/docs/suite-release-pairing.md) for v5;
documentation successors on main do not replace
them. Tags and public Releases require separate authorization. When verified
`v5.0.0` tags and Release records are available, use them for the published
selection, validation and limitations; a package version alone is not a release.

| Baseline | Meaning |
|---|---|
| `v1.0.0` | Historical EdgeForge v1 freeze: CRUD flow, Step 8 Build & Run, Step 2 upload hardening, and constrained passthrough-router authoring. |
| `v1.5.0` | Phase 4 Engine MCP generate baseline, including bounded MCP `generate_app` integration and fallback hardening. |
| `v2.0.0` | Knowledge Server / Knowledge Assist field-suggestion MVP baseline. |
| `v3.0.0` | UX v3 Knowledge Assist, broader generated-artifact review, Evidence Trail v1.1, Docker Studio runtime, and Kafka router Studio support. |
| `v4.0.0` | Enterprise-ready shared-mode foundation: per-session SQLite state, server-owned workspaces, CSRF/cookies, root-constrained Engine calls, quotas/retention, audit hooks, and L2/L4/L5 smoke entries. |
| `v4.1.0` | Regen-preview maintain baseline: durable managed generated baseline, Engine Change Plan render, approve-to-apply flow, and L5 regen addendum. |

See [CHANGELOG.md](CHANGELOG.md) for the milestone narrative.

## What Studio Does

Studio is a lightweight local or shared-mode authoring service that:

1. Captures project setup, archetype, target profile, and Engine context.
2. Ingests upstream contracts from URL, upload, paste, or edge-contract artifacts.
3. Authors supported flows:
   - CRUD canonical entity flow
   - constrained passthrough-router flow
   - Kafka integration / router flow
   - file fixed-width / CSV edge contracts
   - XML/XSD edge contracts
   - SOAP/WSDL adapter-only and canonical operation mappings
4. Writes a valid EdgeForge package to disk or ZIP.
5. Exports Evidence Trail v1.1 generated-artifact metadata.
6. Validates and generates through EdgeForge Engine.
7. Optionally builds/runs generated apps in local single-user mode.
8. When `EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED=true`, renders the Engine Change
   Plan for a previously generated baseline and can approve additive apply.

Knowledge Assist remains OFF by default. With KA OFF, Studio makes no live KS
calls and shows no KA UI noise. With KA ON, Studio can use the local Knowledge
Server for field, validation, rule, mapping, transform, and advisory review
surfaces while keeping the author in control of persisted decisions.

## Relationship To EdgeForge Engine

```text
EdgeForge Studio                   EdgeForge Engine
-------------------------------    --------------------------------
Collect author intent          ->  Read manifest package
Write manifest + support files ->  Validate, assess, plan, apply, generate
Build & Run generated app      ->  Produce standalone Spring Boot project
```

Studio talks to the Engine through `app/integrations/appbuilder_integration.py`.
Shared mode root-constrains every Engine invocation and forces MCP for generate;
local mode keeps the developer-friendly fallback posture.

Generated applications are standalone. They do not depend on Studio at runtime.

## What EdgeForge does and doesn't do

One reviewed manifest package describes one standalone application generated by
Engine. Studio authors supported interfaces, mappings, declared rules and
handoffs for CRUD, constrained passthrough and Kafka flows. Cross-service calls
are limited to those supported contract paths; this is not arbitrary service
orchestration, complete business-logic generation, automatic legacy-data
migration/cutover, or universal enforcement of every OpenAPI constraint.

Regeneration preserves designated developer-owned extension seams, not arbitrary
edits to generated files. The [newcomer journey](docs/newcomer-journey.md) proves
one executable service hook and additive change at its recorded revisions. Its
managed-copy/build-path and database limitations still apply; selected-release
execution and justified reuse are recorded separately in the November 14
successor results above; later independent approval is recorded separately.

Generated applications need an authenticated TLS gateway with direct application
ports inaccessible to untrusted clients, plus adopter-owned business, object,
tenant and row authorization. Studio's authoring controls do not implement those
policies for an application. No production certification is claimed.

## Wizard Flow

| Step | Scope | Purpose |
|------|-------|---------|
| 1 | All archetypes | Project setup, archetype selection, target profile, output path, local EdgeForge repo path |
| 2 | All archetypes | Upstream OpenAPI or edge-contract ingest |
| 3 | CRUD | Entity and operation selection plus CRUD mapping authoring |
| 3 | Passthrough Router | One inbound operation, downstream targets, route field, equality-match rows, default target, and flat transforms |
| 1-8 | Kafka Integration | Topic/schema ingest, route model authoring, router transforms, shared rules, review, and export |
| 4 | CRUD | Data handoffs / staging-table authoring |
| 5 | CRUD | Downstream interface and edge-contract authoring |
| 6 | CRUD | Business rules and legacy notes |
| 7 | All archetypes | Review, completeness report, and Decision History |
| 8 | All archetypes | Export, validate, generate, build/run, and regen-preview entry point |

## Manifest And Contract Boundary

Studio emits the EdgeForge manifest 2.0 package contract:

```yaml
schema_version: "2.0"
app_archetype: crud | passthrough-router | kafka-integration
```

Studio and Engine are a paired contract at this version: use an Engine release
that supports manifest 2.0. Future concepts must remain additive within that
contract, and Studio must not broaden a wizard surface beyond Engine support.
Saved Studio project snapshots currently use the independent `1.4` contract and remain
reopenable through their supported migration path.

## Deployment Postures

Studio supports two postures:

- **Local single-user** (default): no auth, Build & Run enabled, operator-supplied
  paths honored, intended for localhost development.
- **Shared multi-session**: `EDGEFORGE_STUDIO_SHARED_MODE=true`, signed session
  cookies, CSRF, per-session SQLite state and workspaces, server-owned output
  paths, per-session KS DB, root-constrained Engine invocation, Build & Run
  disabled by default, quotas, retention, and audit hooks.

Shared sessions use **anonymous signed-cookie identity**, not authenticated team
identity. Proxy-header and OIDC adapters are deferred placeholders. An external
gateway can restrict access, but does not map its users into Studio principals;
audit attribution remains session-level. A project-supported authenticated team
service requires separate identity integration and proof.

See [docs/deployment-model.md](docs/deployment-model.md) and
[docs/security-boundary-map.md](docs/security-boundary-map.md) for the operator
contract and security posture.

## How To Run Locally

### Prerequisites

- Python 3.11+
- `pip`
- local EdgeForge Engine checkout

### Setup

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install -c constraints.txt pip setuptools wheel
.venv/bin/python scripts/verify-packaging-toolchain.py
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
```

### Start The Server

```bash
.venv/bin/uvicorn app.main:app --reload --port 8080
```

Then open [http://localhost:8080](http://localhost:8080).

The installed console script is also available after `pip install .`:

```bash
edgeforge-studio --host 127.0.0.1 --port 8080
```

### Point Studio At EdgeForge

In Step 1, set **EdgeForge Local Repo Path** to your local Engine checkout, for example:

```text
/path/to/EdgeForge
```

Studio uses that path for manifest validation, `appbuilder assess`, Change Plan
preview/apply, and generation.

## Docker

Studio includes a Docker Compose dev runtime for live-reload local work. It
expects Studio, Engine, and Knowledge Server to be sibling repositories by
default:

```text
GitHub/
  EdgeForgeStudio/
  EdgeForge/
  EdgeForgeKnowledgeServer/
```

Initial v5 distribution is source repositories and tags. These Docker instructions
are for self-managed builds, not official published images or a maintainer-operated
service.

From the Studio repo root:

```bash
docker compose config
docker compose build studio
docker compose up studio
```

Then open [http://localhost:8083](http://localhost:8083).

Docker Compose uses `additional_contexts` to provide the Engine build context to
the Studio image. That Compose syntax is valid and should remain in
`docker-compose.yml`.

The image uses official Python **3.13.16 slim Bookworm**; host installation on
Python **3.11+** remains supported. All Dockerfile FROM stages are multi-platform
index-digest pinned. Official APT security updates still resolve at build time,
so these pins do not guarantee byte-identical rebuilds. Python 3.13's bare venv
seeds pip, not setuptools/wheel: keep the explicit constrained toolchain install
in the setup instructions above. See the [Bundle P image proof and remaining
findings](docs/handover-evidence/studio-image-bundle-p-2026-10-11.md) for the
assessed AMD64 artifact, bootstrap behavior and refresh triggers.

The image includes checksum-pinned Apache Maven 3.9.16 under `/opt/maven` for
Studio's local Build & Run, using the copied Temurin JDK 21. Its complete official
distribution (including LICENSE/NOTICE) replaces Debian's Maven package; no
individual Guava JAR is substituted. See the [artifact-bound Maven image evidence](docs/handover-evidence/studio-maven-image-remediation.md)
for compatibility proof, targeted Guava remediation and remaining open findings.
This is not whole-image or M2 clearance. Maven creates its writable cache in the
non-root user's `$HOME/.m2`; shared-mode Build & Run remains disabled by default.
The lean image does not provide Java font-rendering support by default. Adopter
code that renders or measures text (including some report, PDF, or spreadsheet
paths) needs an explicitly extended and assessed image; this does not change
Studio's browser UI fonts or imply that every PDF/Excel workflow fails.

`EDGEFORGE_STUDIO_IMAGE_PREBUILT` makes the image launch smoke skip its Dockerfile
build and test only the supplied image. To prove a changed recipe, first make and
identify a fresh image build from that source, then pass its tag to the smoke.

If you run a raw `docker build` instead of Compose, pass the Engine context
explicitly:

```bash
docker build \
  --build-context edgeforge_engine=../EdgeForge \
  -t edgeforge-studio:local .
```

The Compose service:

- runs `uvicorn app.main:app --host 0.0.0.0 --port 8083 --reload` (the
  `--reload` file-watcher is this dev runtime only -- the image's own `CMD`
  does not carry it)
- publishes the port to `127.0.0.1` by default, not every host interface --
  local mode has no auth, by design; override with `EDGEFORGE_STUDIO_BIND_HOST`
  if you deliberately want it reachable from other devices
- runs as a non-root user matching `EDGEFORGE_STUDIO_APP_UID`/`_APP_GID`
  (default `1000`/`1000`, see `.env.docker.example`). The bind mounts below
  keep the *host's* ownership regardless of anything set in the image, so if
  you hit permission errors writing exports, set those to your own host user
  (`id -u` / `id -g`) and rebuild
- bind-mounts this repo to `/workspace/EdgeForgeStudio`
- bind-mounts the sibling Engine repo to `/workspace/EdgeForge`
- bind-mounts the sibling Knowledge Server repo to `/workspace/EdgeForgeKnowledgeServer`
- defaults empty exports to `/workspace/data/GeneratedApps`
- mounts generated packages/apps to `${HOME}/Documents/EdgeForgeGeneratedApps`
- configures container-safe Engine MCP and KS paths

This is a local, single-operator dev profile, not a shared/production
deployment target: build the `Dockerfile` directly with your own
orchestration for that, matching `APP_UID`/`APP_GID` to its runtime user.

## Running Tests

```bash
pytest tests/ -q
pytest tests -q -m "not smoke"
pytest tests/smoke/test_l2_two_session_smoke.py -q -m "smoke and l2"
```

Cross-repo L4/L5 smoke tests are manual/nightly checks and skip cleanly when the
Engine/KS dependencies are absent.

## Development Utilities

```bash
make setup
make test
make lint
make sbom
make audit
make lock
make clean
```

`make lint` runs Ruff with the shared suite baseline; the CI Ruff job is
non-blocking during this handover polish pass.

## Documentation

- [One local newcomer journey](docs/newcomer-journey.md) — open a synthetic sample, run it, author an additive change, and prove the supported developer-owned seam survives regeneration.
- [docs/README.md](docs/README.md) — documentation navigation index
- [docs/test-results/README.md](docs/test-results/README.md) — dated proof archive index
- [docs/studio-architecture.md](docs/studio-architecture.md) — Studio architecture overview
- [docs/studio-context.md](docs/studio-context.md) — current implementation baseline and handoff context
- [docs/deployment-model.md](docs/deployment-model.md) — local/shared deployment posture
- [docs/handover-evidence/README.md](docs/handover-evidence/README.md) — enterprise handover evidence
- [Publication preparation](docs/publication-preparation.md) — remaining maintainer decisions and unpublished starter drafts
- [CHANGELOG.md](CHANGELOG.md) — milestone summary
