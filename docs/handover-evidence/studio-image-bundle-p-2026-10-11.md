# Studio Bundle P image transition - 2026-10-11

Candidate **EF-V5-M2-STUDIO-IMAGE-BUNDLE-P**, revision **1**. Implements the
maintainer-approved proposal revision 2, manifest SHA-256
`9eda14e637acad74b8a713afffa7a672c66afe7a3b42b630074230d4297a05ec`;
all six inputs verified. The private proposal and its independent review are
retained with this campaign. That proposal review is not implementation approval.

**Partial correction with OPEN findings, not M2 clearance, risk acceptance or
release approval.** Only linux/amd64 was assessed, emulated on a Darwin arm64
Docker Desktop host. Multi-platform FROM pins preserve recipe architecture
selection; they do not establish other-platform compatibility or clearance.

## Source and image identity

| Input/artifact | Exact identity |
|---|---|
| Studio base | `260af2983eb74c8f0eb38fe757120086a3228528` |
| Image-tested Studio | `98a50bf0204976043f1d69580113a30c390e1b31` |
| Frozen clean merged Engine archive | `30d25d055c48001e6478493c8993d1e029d4df8f` |
| Actual OCI index / local image identity | `sha256:1a2a15d0adb3437c9c12afc42022cc2ba560c541e65b0287eb3eef0100bfb567` |
| Actual AMD64 OCI platform manifest | `sha256:c83ba4ef967059339bdf5b8079a800686f19c18d25bfd26cfab890f6d1d6b3e7` |
| Actual image config | `sha256:145242491c522c875bd74a765724cbdb6d38b308c47920a5bbbaf899dc95f8dd` |

The [receipt](studio-image-bundle-p-2026-10-11-receipt.json) contains verified
compressed OCI layer digests, separately verified filesystem diff IDs,
stage/index/platform/config identities, source/archive hashes and tool provenance.
Scanner serializer `5b037343...` is **not** the OCI platform manifest.
The committed base projection retains registry/platform/config identities; full
base environment and build history remain in the hash-bound private input rather
than duplicating upstream public signing fingerprints in the summary. No scanner
allowlist or secret-check exemption is introduced.
`verify_image_oci.py` verifies the archive's index, unique AMD64 manifest, config,
blob hashes/sizes and decompressed diff IDs. No registry publication occurred.

One local full build was used; no corrective full build was needed. The tested
commit contains the recipe changes and unchanged packaged `app/`/constraints.
Later PR commits add only proof tools/tests and documentation/evidence, which the
recipe does not copy into packaged application code. The final reviewed PR head
is recorded in its body, separately from the image-tested commit. Engine is a
**provisional compatibility pin**, not Suite final release selection.

Replay-provenance clarification (2026-10-14): `proof_tools_sha256` records the
original four executor snapshots, verified against source
`ae99f6d3924ba01429edbdb25712e7cfffb38583`; it does not describe later replay code.
The reducer pins those recorded identities instead of hashing the current working
tree. This preserves the historical receipt unchanged when a compatible shared
verifier is edited. The retained `--check` replay is a regression check; changes
to actual computed evidence still fail it. No historical result is upgraded.

## Recipe and bootstrap contract

Both Python stages use official `python:3.13.16-slim-bookworm` index
`a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641`;
AMD64 manifest `f040863673aea2570c3ff6a5c3fb4c673a016cbc5375005ad145915922b6b78a`.
The JDK stage index remains
`3e3c176ffed168beb42c607be9bc1639b466cf00261a0fb04425562c9d0c5c2b`;
AMD64 manifest `442a743d9272be15c9872915eab0f7a1b6bb45b7c16c613acf172e2d7483061d`.
The actual copied runtime is Temurin **21.0.12.1+1-LTS**. All 248 regular JDK
files match the previous advisory-bound comparison, including the previously
explained recipe-modified CDS archive; this is not a new blanket JDK exclusion.

Retained: pip **26.2.1**, setuptools **83.0.0**, wheel **0.48.0**, verified Apache
Maven **3.9.16**, official APT upgrades, curl/git/build-essential, non-root UID/GID
1000 defaults and existing supported host Python 3.11 setup. Pip availability was
checked once at task entry; no newer release was selected. No custom unvendoring,
bootstrap deletion, backport, app/dependency/schema change or font restoration.

Python 3.13's upstream ensurepip contains only pip 26.2.1, not the old pip 24.0
or full setuptools 79.0.1 bootstrap wheels. A bare venv no longer seeds
setuptools/wheel. The offline proof creates a venv without pip, runs ensurepip,
then explicitly installs constrained pip/setuptools/wheel/packaging from four
SHA-256-verified official local wheels with network disabled. `pip check` and a
synthetic wheel build pass. Ensurepip and venv remain supported.

Active pip and the archived seed share the same inspected private msgpack,
pkg_resources and urllib3 bytes. Duplicate metadata is retained: active wheel
0.48.0 differs from setuptools' private wheel 0.46.3. A name-keyed inventory must
not overwrite that distinction. Archive and installed-code checks, not missing
standalone distribution metadata, support the copy conclusions.

APT uses official Bookworm/bookworm-updates/bookworm-security repositories.
The receipt records the actual sources and all installed dpkg versions. Lists
are removed by the existing recipe, so the resolved InRelease/package-index
hashes are unavailable; comment snapshot dates in `debian.sources` do not mean
the live URIs are frozen. **FROM digest pins alone do not make rebuilds identical**:
APT resolution, package downloads and artifact availability can change.

## Executed proof and retained failures

- Actual image imports, tool versions and `pip check` pass as UID 1000.
- Existing fresh-image launch smoke: **1 passed**; packaged source, no source bind
  mounts, loopback-only publication. Supplying its prebuilt tag avoids a second
  build; the preceding recorded Dockerfile build establishes recipe proof.
- Network-disabled offline bootstrap and byte/copy/behavior probe pass.
- Real Studio `/project/open` -> `/export/write` -> `/export/generate` ->
  `/export/build` -> `/export/run` -> `/export/stop` passes. The representative
  synthetic FS input is temporarily jobless with legacy-compatible Boot 4.1.1;
  handoffs/downstream interfaces are removed only in that temporary proof input.
  This does not prove Batch profiles, arbitrary contracts or a browser journey.
- Separate `mvn clean verify`: **1 executed test, 0 failures/errors/skips**.
  Studio's unchanged build route then packages with `-DskipTests`; packaging is
  not counted as test execution. Surefire reports were retained before clean.
- Account POST returns **201** with all synthetic fields; GET returns **200**
  with matching persisted fields; absent ID returns **404**, through Studio's
  normal generated-app proxy. KA remains OFF; no KS was invoked.
- Image-environment regressions: **487 passed, 4 skipped, 4 failed**. All four
  failures are Node-dependent DOM tests: Node is not shipped in this runtime
  image. They must pass in host/CI validation and are not counted as image passes.
  The four skipped cases are reported by pytest, not substituted for proof.

The initial campaign failed six tests: three lacked the Compose fixture, three
exported beneath `/tmp` outside Docker's permitted root. Its first retry still
failed those three. The goal paused. The maintainer authorized one bounded
proof-harness repair/revalidation cycle. Pytest setup initially failed before
executing tests because the permitted output parent directory was absent;
creating that task-only parent completed setup. The three original failures then
passed using `--basetemp` beneath `/workspace/data/GeneratedApps`, without
disabling or modifying the Docker guard.

The initial behavior probe and retry incorrectly caught `ValueError` instead of
`http.cookies.CookieError`; both errors remain retained. The repaired probe
captures the actual rejection and succeeds. The historical probe script remains
byte-identical so #311's checksum-bound replay is not rewritten.

Host/final-head test and CI results are recorded in the PR body. Earlier
2359-passed host evidence predates final tooling edits and is not final-head
approval. No full Suite L5, native accessibility run or final-pair acceptance.

## Assessment and supported dispositions

Checksum-verified **Syft 1.52.0 / Grype 0.119.0 / Trivy 0.74.0** ran locally;
only public tool/advisory databases were downloaded. No private image, source,
SBOM or inventory was uploaded. Database hashes/dates and actual round-two times
are retained. Both rounds used the same actual image and frozen databases:
identical complete Syft artifact lists, byte-identical summaries and matching
normalized ledgers. A failed first comparison caused by a per-round source-hash
field was corrected by comparing the retained inputs, not by rescanning.

Inventory: **166 Debian packages, 106 Python packages, 52 Java archives**, copied
JDK, and 18 imported Python SBOM records. [Summary](studio-image-bundle-p-2026-10-11-summary.json)
and [lossless ledger](studio-image-bundle-p-2026-10-11-ledger.json) retain:

- **1,008** active Grype observations.
- **2,473** ignored Grype observations and their kernel-header exclusion rule.
- **3,486** Trivy Debian observations, including 3 critical and 270 high matches.
- **6** inventory-unresolved Python alerts; embedded code is not absent.

These overlapping counts are not added as vulnerabilities. Trivy result types
are Debian, Python and JAR (no JAR vulnerabilities in this observation). Scanner
silence, ignore rules, no-fix and vendor postponed/no-DSA states do not accept risk.

The [delta](studio-image-bundle-p-2026-10-11-delta.json) maps **every one of 3,375
historical groups** to current identities or explicit not-observed status and
retains all **103 family owner decisions**, including zero-match coverage entries.
Different databases mean count differences are not attributed wholesale to P.
The old #311 records remain immutable: 32 identities were then 11 OPEN / 21
supported. This candidate's conservative current dispositions are **3 remediated,
14 supported-not-affected, 15 OPEN**:

- **Remediated:** CVE-2025-15366 IMAP no-send newline rejection and CVE-2026-6019
  Morsel output neutralization, verified against actual behavior and official
  3.13.16 module hashes; CVE-2026-59890 old full-setuptools bootstrap replacement,
  with actual 83.0.0 normalization proof and stripped pkg_resources distinction.
- **Supported:** twelve inherited JDK advisory-specific conclusions and two
  unchanged vendor-subset conclusions, checked against actual bytes. No double
  remediation credit or universal JDK/native clearance.
- **OPEN:** alternate-alphabet base64 deprecation (still accepts original chars),
  padded-base64 caller strictness, POP3, complete target-specific cleanup/file-flags
  applicability, embedded Expat 2.8.5 and pip's private urllib3 2.7.0 in both active
  and seed copies. A standalone urllib3 update would fix neither private copy.
- **Seven prior supported CPython identities remain historical conclusions but
  are OPEN for this changed candidate**, rather than auto-carried from different
  bytes or scanner silence. Exact advisory/backport applicability to this line
  remains the named runtime-owner follow-up; this does not declare new exploits.
- **21 additional old-bootstrap associations** stay separately traceable. The
  obsolete archives are verified absent, but successor advisory-range/applicability
  reconciliation remains explicit OPEN owner work, not blanket clearance.

Newly encountered **CVE-2026-77214** (Expat XML_ParseBuffer) remains OPEN for
separate system and embedded-copy review. The current CPython cleanup match lists
a newer 3.15 fix but is not presumed solved by the approved 3.13 bundle.

## Coverage and next-owner queue

The receipt covers installed OS/Python inventory, named active/archived private
copies, copied JDK regular-file comparison and final Maven archives. Scanner
coverage is not proof of all native libraries/extensions, shaded JARs or future
Maven plugins/transitives. Whole discarded Python/Maven/JDK build stages and the
host kernel are not fully assessed by final-image scanners. Other architectures
remain unassessed. **Java font rendering remains unavailable by default**;
restoring fonts needs a separately approved and assessed compatibility change.

Runtime/security owner: resolve the exact stdlib caller/native/Expat and seven
candidate carryforward questions. Packaging owner: upstream pip with supported
private urllib3 fixes and successor bootstrap reconciliation. Image/security
owner: prioritize runtime TLS/parser consumers (curl/OpenSSL/glibc and system
Expat), then compiler/binutils/headers and other native/build families using the
retained complete queue. No risk disposition is made by these assignments.

## Reproduction, retention and refresh

Use the **reviewed PR head**, not the image-tested pre-evidence commit, for these
tools. Obtain the private retained directory through its owner; public checkout
alone cannot replay raw scanner observations. The existing private EdgeForge
Open-Source Artifacts folder contains `Studio-Bundle-P-2026-10-11`: image/Engine
archives, official inputs, wheels, tools/checksums, frozen databases, both raw
rounds, CycloneDX SBOM, Maven/runtime/test logs, failed attempts and source copies.
Its original 799-file pause manifest remains immutable; resumed files receive a
separate retention manifest. Host-specific paths are intentionally not committed.

```bash
python3.11 -m scripts.image_bundle_p_report --retained "$PRIVATE_RETAINED" --check
python3.11 -m scripts.image_runtime_dispositions --check
python3.11 -m pytest tests/test_image_bundle_p.py tests/test_image_bundle_p_report.py tests/test_verify_image_oci.py -q
```

The first command revalidates the actual OCI bytes, both scanner rounds, official
source/vendor copies, executed proof and inherited mappings; it never scans or
builds. All eleven required stdlib records must have the expected installed path
and checksum-matched official source before dispositions can be computed; missing,
import-error, unsupported-path or stale comparison records fail closed. Independent
R0 review exposed this validation gap; the actual retained records were complete
and matched, so the repair changes neither image bytes nor finding outcomes.
Historical #310 missing raw inputs remain unavailable; P does not recreate
or use them to silently upgrade historical dispositions.

For a **new assessment artifact**, freeze clean Studio and Engine archives, use
the reviewed recipe and named `edgeforge_engine` context, and record exact inputs:

```bash
docker buildx build --platform linux/amd64 --build-context edgeforge_engine="$FROZEN_ENGINE" --metadata-file build-metadata.json --iidfile image.iid --load -t studio-new-assessment .
docker save -o image.tar studio-new-assessment
python3.11 scripts/verify_image_oci.py --archive image.tar --index "$RECORDED_INDEX_DIGEST"
EDGEFORGE_STUDIO_IMAGE_PREBUILT=studio-new-assessment python3.11 -m pytest tests/smoke/test_docker_image_launch_smoke.py -q -m smoke
```

These commands do not recover the dated image digest. Follow the local-only
scanner procedure in [the original assessment](studio-image-assessment.md) with
verified binaries and declared frozen databases. Inside a task-owned, mount-free,
non-root container, run `image_bundle_p_probe.py` and `image_bootstrap_proof.py`
with networking disabled after copying only proof tools and verified wheels.
Run `maven_image_build_run_proof.py --help`; the recorded journey adds
`--run --jobless --exercise-account` to the FS/legacy-compatible case. Maven
resolution needs its declared network/cache; bootstrap proof does not.

Refresh on relevant advisory/vendor changes, any base/runtime/constraint/JDK/
Maven/recipe change, new supported platform, or selected release pairing. Pin
updates require compatibility proof and reassessment, not unattended automation.
**The final Suite-selected Studio/Engine pair must be rebuilt and assessed**;
this provisional run cannot be renamed final acceptance. No merge, image
publication, tag, release, settings change, KS lane or follow-on goal is started.
