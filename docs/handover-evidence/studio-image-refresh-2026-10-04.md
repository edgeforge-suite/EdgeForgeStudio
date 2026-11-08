# Studio image refresh and Expat proof - 2026-10-04

**EF-V5-M2-STUDIO-IMAGE-REFRESH-S1, revision 1. Builder evidence, not approval.**
One fresh supported-recipe AMD64 image was built and assessed completely within
the stated filesystem scope. Ten historical Debian Expat groups have supported
backport fixes; five current system Expat groups remain OPEN. The independent
review and required final-head CI are separate delivery gates, recorded outside
the reviewed commit. This is not M2 clearance, risk acceptance, an image
certification, a selected v5 tuple, or permission to deploy Studio.

## Evidence and identity

The [identity/command receipt](studio-image-refresh-2026-10-04-identities.json)
records resolved base indices/platforms/configs, all sixteen compressed layer
digests and distinct uncompressed DiffIDs, raw file hashes, tools, databases,
commands/outcomes, native inspection, audit and compatibility proof. The
[reduced SBOM/findings summary](studio-image-refresh-2026-10-04-summary.json),
[lossless current ledger](studio-image-refresh-2026-10-04-ledger.json) and
[baseline delta](studio-image-refresh-2026-10-04-delta.json) are the machine-readable
assessment. Large raw reports, full CycloneDX inventory and databases are not
committed or uploaded.

| Identity | Exact value |
|---|---|
| Image-tested Studio source | `a333ab58433909f6ab224585be6471ed2c184aa2` |
| Image-tested Studio tree | `8c5c0e8d37857de737cb3ae8f075218583a58a14` |
| Read-only Engine archive pin | `ab41a02fc854f89681e0473d9914e9e16528c3c2` |
| Corrected proof-helper source | `c58e3c057ebc4adcf2732708d46a41c67fbc9a11` |
| Corrected proof-source tree | `82650e93d3ca8227ca3424e039ab64bf64b26515` |
| Actual local image / OCI index | `sha256:145acf7614b67f146959eb1b964c4f0a6eea5f996384025d4968d3a6dddfb62e` |
| Actual AMD64 OCI platform manifest | `sha256:07a6d9c444dee382aab67461f14987bee1aec0043784fcea640d96ffdfc849cc` |
| Actual image config | `sha256:1dac71e187a03e7f13468bd52feeb59328545959ee22bfe11f04a0be7970f8f9` |
| Scanner's Docker-schema-2 serialization | `sha256:a0969e988f6bfeb9b9cb7b485def0a1cf442b65dfefabaab7b349806a163a5ab` |

The schema-2 digest is not substituted for the actual OCI platform identity.
Descriptor sizes and SHA-256 hashes of the actual OCI blobs, config and compressed
layers were checked; decompressing each layer independently reproduced its
config DiffID. Scanners identify the same config, ordered DiffIDs and platform.
The Engine tar's embedded Git commit was checked before use. Later helper/tests
and evidence edits do not change any copied image inputs: Dockerfile,
`.dockerignore`, requirements/constraints, Maven installer/packaging verifier,
and the application tree remain identical to the image-tested source. The final
PR head/tree and that comparison are in the external review packet, not guessed
from this earlier tested source.

### Fresh recipe output

One initial build, zero corrective builds. `--pull --no-cache --platform
linux/amd64` refreshed both official tags and executed fresh Bookworm APT
resolution; the log records fetched InRelease/Packages and actual u4 installation.
No recipe, lock, workflow, application or sibling repository changes were needed.
The existing Dockerfile already upgrades APT packages; no manufactured recipe
fix is claimed. UID/GID are 1000/1000. Build started at `2026-10-05T00:55:40Z`;
the receipt contains its completion/log identity and BuildKit provenance.

| Installed component | Historical #308 image | Fresh image |
|---|---|---|
| CPython | 3.11.16 | 3.11.17 |
| Debian libexpat1 | 2.5.0-1+deb12u3 | 2.5.0-1+deb12u4 |
| Debian libpcre2-8-0 | 10.42-1+deb12u1 | 10.42-1+deb12u2 |
| CPython embedded Expat, separately probed | 2.8.3 | 2.8.5 |
| Copied Temurin runtime | 21.0.12.1+1-LTS | 21.0.12.1+1-LTS |
| Official Apache Maven | 3.9.16 | 3.9.16 |

The first three rows are the complete changed-version list in the Syft catalog;
the embedded Expat row comes from native inspection, not a standalone catalog
entry. Same-version artifacts can still differ. Resolved official base identities
are in the receipt; floating tags do not promise digest-reproducible rebuilds.

## Concrete Expat disposition

Official [Bookworm package metadata](https://packages.debian.org/bookworm/libexpat1)
and the [Debian security tracker](https://security-tracker.debian.org/tracker/source-package/expat)
were fetched again. The official security-pool
[u4 source descriptor](https://security.debian.org/debian-security/pool/updates/main/e/expat/expat_2.5.0-1+deb12u4.dsc)
names the retained source archive and SHA-256
`f522d550e0a3ff992c293f2c49d44a1248985863d64005f91e086afc5d295908`.
Its u4 changelog names all ten exact backports below; the frozen tracker marks
Bookworm resolved at u4. Actual `dpkg-query` is u4 and `dpkg --compare-versions`
confirms it is at least u4 using Debian ordering. The installed native runtime
reports `expat_2.5.0`, as expected for a backport rather than an upstream-version
bump.

The actual `/lib/x86_64-linux-gnu/libexpat.so.1.8.10` bytes match the official
[AMD64 u4 binary package](https://security.debian.org/debian-security/pool/updates/main/e/expat/libexpat1_2.5.0-1+deb12u4_amd64.deb):
library SHA-256 `453732cb225bc46f9337066d782118d24194bccee4c85b59eccf7e8714b5e62f`;
downloaded package SHA-256
`ed010cc41577d75ab01cccc6afa93496d9a99f1e16bd469caf58e1b81fddae80`.
`dpkg -V` has only three missing documentation files, explicitly retained in the
receipt, because the unchanged recipe removes `/usr/share/doc`. No library
difference was accepted.

| Historical candidate advisory | System libexpat1 u4 conclusion |
|---|---|
| CVE-2024-28757 | Supported fixed: exact u4 vendor backport |
| CVE-2025-59375 | Supported fixed: exact u4 vendor backport |
| CVE-2026-24515 | Supported fixed: exact u4 vendor backport |
| CVE-2026-25210 | Supported fixed: exact u4 vendor backport |
| CVE-2026-32776 | Supported fixed: exact u4 vendor backport |
| CVE-2026-32777 | Supported fixed: exact u4 vendor backport |
| CVE-2026-32778 | Supported fixed: exact u4 vendor backport |
| CVE-2026-45186 | Supported fixed: exact u4 vendor backport |
| CVE-2026-66046 | Supported fixed: exact u4 vendor backport |
| CVE-2026-93990 | Supported fixed: exact u4 vendor backport |

These ten current non-reports corroborate the package/backport proof; their
disappearance alone is not the proof. Delta rows retain the historical group and
observation references, current references where present, vendor fields, owner
and review trigger. None is extrapolated to embedded Expat.

| Other observed system advisory | Current Grype / Trivy severity | Disposition |
|---|---|---|
| CVE-2023-52426 | Negligible / LOW | OPEN; preserve package match and vendor qualification |
| CVE-2025-66382 | Medium / MEDIUM | OPEN; vendor postponed is not clearance |
| CVE-2026-102633 | Medium / MEDIUM | OPEN; vendor open, investigate affected consumer/copies |
| CVE-2026-41080 | High / LOW | OPEN; severity conflict and vendor no-dsa retained |
| CVE-2026-56132 | Medium / MEDIUM | OPEN; vendor postponed is not clearance |

No additional system Expat group appears beyond these fifteen historical/current
identities. The ledger preserves original fix/severity/vendor fields rather than
replacing them with this table. `pyexpat` independently reports `expat_2.8.5`;
its extension links libc, not system libexpat. Its hash and linker output are
retained. **Embedded applicability remains OPEN**, specifically including
CVE-2026-102633; a Debian u4 fix cannot cover CPython's separate code. Neither
matching nor non-matching scanner coverage establishes complete embedded closure.

## Assessment and bounded comparison

Official retained archives were verified against the correct assessor-host
checksum entries and their embedded executable bytes before reuse. Host is
Darwin ARM64, target is Linux AMD64; scanners were not upgraded.

| Official tool release | Correct host archive SHA-256 |
|---|---|
| [Syft 1.52.0](https://github.com/anchore/syft/releases/tag/v1.52.0) | `014d561b6d13059124155f74a6c5a9a99501f5e209313638dd884f39eb418ee6` |
| [Grype 0.119.0](https://github.com/anchore/grype/releases/tag/v0.119.0) | `500c9b2b6c089d21481815f57a553fabbd441ec7d1e79d95e3aaf40c3bfc7e36` |
| [Trivy 0.74.0](https://github.com/aquasecurity/trivy/releases/tag/v0.74.0) | `1caada5e0e2091909357c7525d3aa76f4b660b13821bc143b190c7483e31cc11` |

Public databases were downloaded once before this campaign, frozen read-only and
hash-checked before/after each pass. Grype schema v6.1.10 was built at
`2026-10-04T08:11:47Z`; Trivy DB v2 updated at
`2026-10-04T19:39:34.715623444Z`; Java DB v1 updated at
`2026-10-04T01:44:08.185725365Z`. Exact database/import/metadata hashes and download
times are in the identity receipt. Schema advancement is not a scanner upgrade.
Final advisory observation cutoff is the recorded second Trivy completion.

Two passes on the same new artifact/frozen databases produced byte-identical
reduced summaries, identical complete Syft artifacts and equivalent complete
normalized ledgers. Only raw source-report hashes were excluded from normalized
equivalence, not findings, identities or classification. Existing report and
ledger validators passed both; no invalid scan is counted. Updates, external
inventory queries, Trivy telemetry/version checks and remote image fetching
during scans were disabled. No inventory was sent to an advisory service.

| Coverage / observations | Retained result |
|---|---|
| Syft inventory | 346 identities: 166 Debian, 109 Python, 52 Java archives, 19 binaries |
| Grype active | 1,046: 1,039 Debian and 7 CPython binary observations |
| Grype ignored | 2,315, including complete default linux-libc-dev rule observations |
| Trivy | 3,362 Debian and 6 imported/unresolved Python observations; Java archive zero alerts |
| Complete cross-scanner ledger | 6,729 observations, 3,375 groups, 103 owned family decisions |
| Native/vendor inspection | 18 pip-vendor declarations, 541 vendor-file hashes, 32 native-extension hashes |

Counts overlap and are not independent vulnerabilities. Original severity,
fix/range, alias, source positions and ignored-rule data remain lossless. All
current groups are `open/unassessed`; no current exclusion or risk acceptance is
introduced. The ten supported historical Expat fixes are reconciled separately,
not used to erase other observations. Integrity projection rejected eight
negative controls: dropped active/ignored findings, changed severity, dropped
group/inventory, missing owner, unsupported exclusion and changed vendor status.

The historical #308 ledger was replayed from hash-verified retained raw reports,
tools/databases and #307 curl proof; its bytes match the committed historical
ledger. No historical proof was changed. That image used Studio
`f22f941d0981135e4f3fa24313266449418e59db`, Engine
`584e4bf635ac12821496a52d20c3a03a6e73a92c`, and cutoff
`2026-10-01T16:30:29Z`, unlike this source/image/feed pair.

The delta compares component/type/advisory identities, not scanner count
subtraction: 3,335 unchanged observation signatures, 22 changed metadata/version
signatures, 18 newly reported groups and 17 currently non-reported groups. The
last categories are detection/catalog changes, **not risk-reduction totals**.
Seventeen new groups concern GCC binary packages/CVE-2026-95619 at unchanged
versions; one concerns CPython/CVE-2026-12345. The non-reports are the ten verified
system Expat backports, six CPython groups and one PCRE group; only Expat receives
the independently supported fix conclusion. Feed drift, range changes and
same-version artifact changes are not apportioned without proof. A separate
disposition delta explicitly maps all eighteen old curl exclusions to current
OPEN groups even where the observation signature is unchanged. No old curl
inapplicability conclusion is automatically reused.

### Remaining owner decisions

Every cataloged family has an owner, specific question, evidence sources and
review trigger in the ledger. The owner is the Studio maintainer; adopter
security owns any eventual exposure/risk decision. No acceptance is implied.

| Decision surface | Required next decision / trigger |
|---|---|
| Runtime/native OS families, remaining Expat, curl | Map exact binary consumers and Bookworm backports per advisory; changed package/range/use or final pair triggers revalidation. No-dsa/postponed/wont-fix is not inapplicability. |
| CPython 3.11.17 and embedded Expat | Verify PSF 3.11 fixes and embedded/native/parser paths for all seven current CPython groups and embedded advisories. Newer-feature-line fix strings are not verified 3.11 backports; any transition needs its own gate. |
| Pip vendor / unresolved Python | Bind msgpack 1.1.2, setuptools 70.3.0 and urllib3 2.7.0 imported identities and six observations to actual copies/functions; installed constraints audit cannot clear pip-vendored code. New wheel/advisory/copy triggers reproof. |
| Copied JDK 21 | Map exact Temurin build to vendor CPU advisories and native/TLS/font consumers; zero matches is coverage UNKNOWN, not JDK clearance. |
| Maven archives, plugins, generated app | Preserve all shipped archive identities and control applicability; downloaded plugins/transitives and other generated profiles require separate assessment. No Java zero-alert clearance. |
| Build-oriented packages / linux headers | Shipped compilers, utilities and ignored linux-libc-dev headers are not a container kernel or automatically unreachable. Assess header/compiled-product and runtime use separately; host kernel and build-stage coverage remain unknown. |
| Native launchers / unrecognized embedded code | Inventory includes shipped alternate-platform native artifacts; map callable platform/use paths before an absence/removal conclusion. |
| Pin versus float / distribution | Choose digest retention/update policy versus fresh supported-tag patch intake for the final pair. A float rebuild is not digest reproducibility; any major/distribution/removal transition requires compatibility review. |

## Proof on the actual image

The existing image launch smoke ran with `EDGEFORGE_STUDIO_IMAGE_PREBUILT`
explicitly set to the new image ID and bound to the new build receipt: **1
passed**, no second build. The task-owned proof container used that same image,
normal UID/GID 1000, no mounts and no host-published port; actual startup and
writes to `/home/appuser/.m2` and `/workspace/data` passed. Source mounts did not
hide image contents; inspected Python package consistency passed.

The committed synthetic project, existing ordinary profile
`springboot-legacy-compatible`, `--jobless --run` and archived Engine Boot 4.1.1
default were used through real Studio project/open, export/write, generate,
build, run, proxy health and stop routes. KA remained OFF, with no KS live calls.
Only temporary proof input omitted file/staging/downstream job handoffs; no
product or generated-app fix was made. Maven `clean verify` executed **1 test,
0 failures, 0 errors, 0 skips** without Python optimization. Studio's actual
Build route subsequently packaged the JAR; its intentional test skip is not
misrepresented as testing. Run/proxy returned HTTP 200 with health `UP`.

Actual generated Boot parent is 4.1.1, packaged H2 is 2.4.240, Batch is absent.
The generated Java target is **17**, packaged application class major is **61**,
and actual image runtime is **Temurin JDK 21.0.12.1+1-LTS**. This is not a Java 17
runtime proof. Corrected-run POM/JAR/dependency-library identities and retained
Surefire XML hashes are in the receipt. Initial-run dependency tree/effective
POM applicability was checked: only the generation-timestamp XML comment in the
POM differs; all other text and every packaged dependency library byte match.
No historical Java 17/21 runtime result is credited to this image.

The sole helper correction retains verified Surefire XML **before** Studio's
packaging clean deletes it and rejects optimized Python before proof actions.
Focused regressions include packaging-clean deletion and optimization 1/2/7
rejection; existing assertions were not weakened. Local focused suite:
**89 passed** after the correction (85 before); helper-only run: **15 passed**.
Changed Python lint and local pinned gitleaks 8.30.1 tree scan also passed.
No duplicate full local suite was run. Required CI remains the unchanged existing
unit/L2/strict-audit job and secret check on the submitted head; approval and exact
CI outcomes belong to the external final-head review record.

Strict `pip-audit 2.9.0` covered all **95 exact reference pins**, zero findings,
zero skipped records, exit 0. Input syntax and PEP-503 identity reconciliation
were checked. Its actual service boundary is GET
`https://pypi.org/pypi/<public-third-party-name>/<version>/json` only: no private
coordinates, source, customer input, image or whole-SBOM upload. This audit is
the constrained reference graph, not OS/vendor/native/JDK filesystem coverage.

### Partial attempts and limits

The identity receipt records failed/partial checks rather than silently crediting
them: initial shell dpkg formatting/missing changelog; one failed changelog URL
recovered through the official source pool; system Python 3.9 lacking strict zip
recovered with required Python 3.11; audit checker's name canonicalization fixed
without another audit; an output-root refusal correctly enforced confinement
before the corrected proof reran beneath the configured root; and the optional
binary checker initially rejecting deliberately removed docs before checking
exact allowed doc removals and unchanged library bytes. No additional image
build or scanner campaign resulted from these proof-tool corrections.

The first image build was actively monitored and completed successfully; later
costly operations used recorded process timeouts bounded by the original hard
deadline. No clock reset is claimed. This campaign does not prove other
platforms, the whole build stage, every native/vendor artifact, all Maven plugins,
Java 17 runtime, PostgreSQL/Kafka or full L5. The historical lean-image font
metrics limitation and prebuilt-image limitations remain: startup proof does not
prove font rendering, and a prebuilt smoke cannot validate its skipped build.
Here that build is independently recorded. No font/A11y correction is claimed.

## Reproduction and retention

For maintainers/contributors/adopters, the committed reduced records identify
what was actually tested and what remains open; they are not a public copy of
the image or databases. Task-local raw files are retained under basename
`edgeforge-studio-image-refresh-20261004-proof`; ask the maintainer for the
hash-identified reports, OCI blobs, databases, official archives/checksum lists,
proof outputs and task-only verifier/projection scripts **before temporary
storage cleanup**. The receipt lists hashes/sizes and exact sanitized commands.
There is no public raw download URL or retention SLA; missing material prevents
exact replay. No image was pushed or signed. A new public-input build/scan is
possible, but floating bases/APT/databases can produce different identities.

From a clean checkout of the image-tested Studio commit, archive the stated
Engine commit into an isolated `$OUT/engine` named build context (check the tar
commit with `git get-tar-commit-id`). Use only synthetic data and task-owned
containers/caches. Set `$TOOLS` to checksum-verified official tools for your
actual host, `$PYTHON` to a constrained Python 3.11 environment, and `$IMAGE` to
the resulting local image ID. The executed build was:

```sh
docker buildx build --pull --no-cache --platform linux/amd64 \
  --build-context edgeforge_engine="$OUT/engine" \
  --build-arg APP_UID=1000 --build-arg APP_GID=1000 \
  --metadata-file "$OUT/build-metadata.json" --iidfile "$OUT/image.iid" \
  --load --progress plain -t edgeforge-studio-image-refresh:20261004 .
```

For exact assessment replay, verify all receipt hashes and reuse its frozen
database directories; do not download replacement databases midway. For a fresh
assessment, download each public DB once first, record metadata/hashes, freeze,
then use the following for each of two passes (`$N` = 1, 2):

```sh
SYFT_CHECK_FOR_APP_UPDATE=false SYFT_EXTERNAL_SOURCES_ENABLE=false \
  "$TOOLS/syft" scan "docker:$IMAGE" --platform linux/amd64 \
  --output "syft-json=$OUT/syft-$N.json"
GRYPE_DB_CACHE_DIR="$OUT/grype-db" GRYPE_DB_AUTO_UPDATE=false \
  GRYPE_CHECK_FOR_APP_UPDATE=false GRYPE_EXTERNAL_SOURCES_ENABLE=false \
  "$TOOLS/grype" "sbom:$OUT/syft-$N.json" --output json \
  --file "$OUT/grype-$N.json"
"$TOOLS/trivy" image --cache-dir "$OUT/trivy-cache" --image-src docker \
  --platform linux/amd64 --offline-scan --skip-db-update --skip-java-db-update \
  --skip-check-update --skip-version-check --disable-telemetry --scanners vuln \
  --list-all-pkgs --format json --output "$OUT/trivy-$N.json" "$IMAGE"
"$PYTHON" scripts/image_assessment_report.py --syft "$OUT/syft-$N.json" \
  --grype "$OUT/grype-$N.json" --trivy "$OUT/trivy-$N.json" \
  --output "$OUT/summary-$N.json"
"$PYTHON" -m scripts.image_findings_ledger --syft "$OUT/syft-$N.json" \
  --grype "$OUT/grype-$N.json" --trivy "$OUT/trivy-$N.json" \
  --output "$OUT/ledger-$N.json"
```

Compare complete Syft artifacts and normalized ledgers, excluding only source
hashes; require identical summaries and unchanged DB hashes. The retained
`scan.py`, `verify_oci.py`, `build_evidence.py` and projection negative-control
receipt make the exact campaign/projection replay inspectable locally. The raw
normalizer output is intentionally not a fresh owner-disposition proof without
the retained vendor/native inputs and verified projection.

Use the current corrected helper copied into a mount-free non-root container,
with the committed synthetic project and output confined beneath the configured
`EDGEFORGE_STUDIO_DEFAULT_OUTPUT_PATH`, `PYTHONOPTIMIZE=0`:

```sh
python /tmp/runner.py --project /tmp/synthetic.edgeforge-project.json \
  --profile springboot-legacy-compatible --proof-root "$PROOF_ROOT" --jobless --run
EDGEFORGE_STUDIO_IMAGE_PREBUILT="$IMAGE" "$PYTHON" -m pytest \
  tests/smoke/test_docker_image_launch_smoke.py -q -m smoke
pip-audit -r constraints.txt --no-deps --disable-pip --progress-spinner off \
  --strict --vulnerability-service pypi --format json --output "$OUT/strict-audit.json"
```

The identity receipt supplies the actual container environment, copying,
inspections, timeouts and outcomes; never mount a changed checkout over the
image. Perform applicable focused regressions and required final-head CI, then
independent exact-head review. No second build is needed merely to review this
retained evidence. Final-pair applicability/reassessment belongs to the later
selected-release campaign. **RP-EVIDENCE-PURPOSE** carries forward to the planned
release-preparation PR; this task does not adopt or expand that proposed contract.
