# Studio image assessment — 2026-09-23

**Status: complete with open findings, not M2 clearance or risk acceptance.** This is
one `linux/amd64` assessment of the shipped Studio Dockerfile, not a multi-platform,
generated-app, KS-container, signature, or release-image assessment. A selected v5
Studio/Engine release pair must be rebuilt and reassessed separately.

## Exact inputs and artifact

| Item | Observed value |
|---|---|
| Studio base source | `56354ce184729c345aa6e4b66a354342c5b66bae` (`origin/main`; clean isolated checkout before the Dockerfile change) |
| Assessed Studio source | PR [#303](https://github.com/santosh-sh/EdgeForgeStudio/pull/303) head (base source plus the Dockerfile update, report helper, and image smoke); use the exact reviewed head from the PR body for reproduction, not the base SHA |
| Engine read-only build context | `d8f50c0edd2d9ec27e7def512455b2881a3c97fe` (clean detached checkout) |
| Platform and build args | `linux/amd64`; `APP_UID=1000`, `APP_GID=1000`; no secrets |
| JDK build-stage source | `eclipse-temurin:21-jdk@sha256:92a2a4d7a928d057e7bd999c418d66c26a34eb9a0442f3ab67721c3f88110b2d` |
| Final-stage base | `python:3.11-slim-bookworm@sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b` |
| Baseline image | `sha256:dae76ad56576d435afbef24ee69e3ec1a8ea3289387ff496f3362f949da006d1` |
| Final image | `sha256:f571cc7702cc700fe5ae8d5ce26f94636f5bf4a3dddfcac65185a31214c5eee8` (`appuser`, 474,676,150-byte Docker-reported size) |
| Final linux/amd64 manifest and config | `sha256:2430bfbddb83886cda1af8e81985d67b4a3e38b9ae822b1eddf709e246e6807e`; `sha256:1b51c45fab81838070f0c803295f259b06c647350e41074d56078905463052c1` |

The final stage contains the Python/Debian base, APT-installed build tooling and
runtime libraries, the copied Temurin JDK, Studio files and the pinned Engine
`appbuilder`. Other files in the Temurin build stage are not copied into the final
image and are outside its advisory count. Maven's Debian dependencies additionally
install `openjdk-17-jre-headless`; the copied Temurin 21 JDK does not replace that
package. Both are inventoried below. The Dockerfile's same-distribution `apt-get
upgrade` brought `tzdata` from `2026b-0+deb12u1` to `2026c-0+deb12u1`; a final
APT check found no further available package updates. This is a compatible package
currency fix, **not** a claim that the advisory backlog was remediated.

## Scanner and database provenance

Only public scanner archives and advisory databases were downloaded. The image,
source, SBOM and private inventory were not uploaded. Syft and Grype read a local
Docker image/SBOM, with online enrichment and automatic DB/app updates disabled
during scanning; Trivy reads only the local Docker daemon and uses `--offline-scan`,
`--image-src docker` and disabled telemetry/updates. The scanners' macOS ARM64
archives were verified against these pinned SHA-256 values from their official
release checksum lists before extraction:

| Tool | Version | Archive SHA-256 | Role |
|---|---|---|---|
| [Syft](https://github.com/anchore/syft/releases/tag/v1.52.0) | `1.52.0` | `014d561b6d13059124155f74a6c5a9a99501f5e209313638dd884f39eb418ee6` | Filesystem inventory, including the copied JDK binary |
| [Grype](https://github.com/anchore/grype/releases/tag/v0.119.0) | `0.119.0` | `500c9b2b6c089d21481815f57a553fabbd441ec7d1e79d95e3aaf40c3bfc7e36` | Advisory matching of the Syft SBOM |
| [Trivy](https://github.com/aquasecurity/trivy/releases/tag/v0.74.0) | `0.74.0` | `1caada5e0e2091909357c7525d3aa76f4b660b13821bc143b190c7483e31cc11` | Independent Debian/Python inventory and advisory cross-check |

Grype DB schema `v6.1.9` was built `2026-09-23T06:31:39Z`, downloaded before
scanning, and its source archive declared SHA-256
`93487281c93d3cb3649878932ff9003991b607136b14cb0943b74846bfd611a8`.
Trivy vulnerability DB v2 was updated `2026-09-23T12:53:55Z` and downloaded
`2026-09-23T19:57:05Z`; its Java DB v1 was updated `2026-09-19T01:01:52Z` and
downloaded `2026-09-23T19:57:47Z`. Advisory databases are time-varying, so a
later reproduction may have different findings even with the same image.

## Coverage and open findings

The [sanitized machine-readable summary](studio-image-assessment-summary.json)
records every affected component/version, severity and fix-state counts, the IDs of
all high/critical matches per component, and whether the component is runtime or
build-tooling oriented. Full Syft JSON, CycloneDX, Grype JSON and Trivy JSON are
generated locally for review but are **not committed**: raw reports can contain
host/cache paths and large private inventories. The summary validator binds all
three reports to the same image and platform: Syft/Grype config and platform
manifest digests, Trivy's OCI index digest, and ordered layer IDs. It also
fails if OS or Python package inventories disagree, the copied JDK or Java
archives are missing, the advisory DB is invalid, or a Grype finding is not tied
to the inventoried image. It preserves Grype's active and ignored results
separately, keeps inventory-unresolved Python alerts open, and rejects
unsupported Trivy result types that contain vulnerabilities. Its failure paths
are unit tested. The two retained Trivy reports contain only `debian` and
`python-pkg` result types; no `jar` result was omitted from this snapshot.

| Installed final-image class | Count | Assessment |
|---|---:|---|
| Debian packages | 222 | Syft/Trivy package-and-version sets agree; Grype and Trivy both report open OS findings |
| Python packages | 109 | Syft/Trivy filesystem package-and-version sets agree; existing strict pinned Python audit remains mandatory |
| Java archives | 98 | Syft inventories Maven/Debian archives; Grype reports two Guava matches |
| Copied Temurin JDK | 1 | Syft identifies `21.0.12+8-LTS` at the copied release file; Grype matches its OpenJDK CPE but reports no JDK-specific advisory |
| Debian Java 17 runtime | 1 of the Debian packages | `openjdk-17-jre-headless 17.0.20.1+1-1~deb12u1`; Debian package matching applies |

The final Grype observation contains **1,100 active package-advisory matches**:
46 critical, 130 high, 193 medium, 19 low, 696 negligible, 16 unknown. By
component class: 1,086 Debian, 12 native Python-binary, two Java-archive.
Fix metadata says 825 `not-fixed`, 261 `wont-fix`, two unknown and 12 `fixed`.
These are **match counts**, not unique CVEs or proven exploitable paths; shared
source packages produce multiple matches. `not-fixed` means no fix in the matched
feed, not proof that no upstream fix exists. `wont-fix` reflects feed/vendor
status, not Studio risk acceptance. All remain OPEN pending separate applicability
and policy review. The high/critical OS groups include curl/libcurl, Perl,
GLib, libc, SQLite and OpenSSL; the summary lists their advisory IDs. All of
these packages remain in the final image; build-tooling orientation does not make
them absent from a deployed container.

Grype also records **1,938 `ignoredMatches`**, all for
`linux-libc-dev 6.1.187-1`. Its applied rule is the scanner's default
`exact-indirect-match` exclusion for the `linux-libc-dev` package matched via
the upstream `linux` kernel-header source; this is not a Studio-approved risk
disposition ([Grype v0.119.0 rule source](https://github.com/anchore/grype/blob/v0.119.0/cmd/grype/cli/commands/root.go#L106-L138)).
The sanitized summary retains this separate count, component, severity groups,
fix-state groups, advisory fingerprint and exact applied-rule fields. Scanner
fix metadata is 1,922 `not-fixed` and 16 `wont-fix`; neither is a Studio risk
decision. Trivy has 1,939 findings
for the same installed package: 1,938 advisory IDs overlap with Grype's ignored
set, and Trivy alone has `TEMP-0000000-F7A20F`. This default exclusion is the
dominant cause of the apparent Grype/Trivy count difference; feed and severity
policies remain additional differences. These are unresolved matches, **not**
1,938 demonstrated exploits and not counts to add to the active or Trivy totals.

The 12 `fixed`-metadata matches are not straightforward compatible image fixes:
ten are Python `3.11.16` binary advisories whose scanner-listed fixes are on
newer Python 3 minor/feature-release lines (`3.13`, `3.14`, `3.15`), not newer
Python majors; no fix is listed for the assessed `3.11` line. This is scan
metadata, not proof that no upstream backport exists. Two Guava `31.1-jre`
archive advisories list an Android artifact rather than an available Debian
JRE-package upgrade. No Python minor-line, JDK-major, base-distribution, Maven
packaging or supported build-capability change is made here. The Grype JDK
zero-match result is **not** a supported
not-affected conclusion: CPE/version advisory matching cannot establish use-path
applicability or vendor-specific Temurin coverage. Native binaries other than the
identified JVM/Python binaries and embedded code without recognized package
metadata are not exhaustively assessed.

Trivy independently reports 3,031 Debian matches (16 critical, 273 high,
1,841 medium, 896 low, five unknown), none with a listed fixed Debian version.
Its imported base-image SBOM raises three Python alerts: `msgpack 1.1.2` (HIGH)
and `setuptools 70.3.0` (HIGH and MEDIUM). Their absence from the **standalone
distribution** inventories does not mean their code is absent from the image.
A read-only, network-disabled inspection of the exact assessed image found
`pip 26.2.1`, pip's vendored `msgpack 1.1.2`, and vendored `pkg_resources`
with `setuptools==70.3.0` in `vendor.txt`; standalone setuptools is `83.0.0`.
Vendored `msgpack.Unpacker` selects the pure-Python `fallback` module and no
vendored msgpack native `.so` is present. The [upstream msgpack fix](https://github.com/msgpack/msgpack-python/commit/2c56ddb5d0025ed481d962c0f5d62d19dec7476d)
changes the native unpacker. Pip's vendored `pkg_resources` is a subset, not the
full old setuptools distribution: the [PackageIndex path-traversal advisory](https://github.com/pypa/setuptools/security/advisories/GHSA-5rjg-fvgr-3xxf)
names code not present in that subset; the old `FileList` sdist path named by
the MEDIUM alert is likewise not in it. These distinctions are applicability
leads, **not** blanket not-affected conclusions. All three alerts remain open
pending artifact-bound, advisory-specific disposition; code presence alone
does not prove exploitability. Trivy does not identify the copied JDK and is
therefore not used alone for Java clearance. Scanner feeds overlap and must
not be summed or equated. The committed summary retains a separate sanitized
Trivy component/disposition breakdown;
per-component fingerprints include every advisory ID, severity and listed fix
so a changed Trivy finding changes the repeatable summary, including a low-
severity finding.

Two scans of the **same** final image identity and unchanged local databases
produced byte-identical sanitized summaries. Grype observations were at
`2026-09-23T15:11:50-05:00` and `15:12:58-05:00`; Trivy observations were at
`15:12:09-05:00` and `15:13:07-05:00`. Both rounds retained 222 Debian, 109
Python, 98 Java archives, the copied JDK, 1,938 rule-excluded Grype matches,
and the same open finding groups.
This is repeatable *inventory/coverage*, not a timeless advisory verdict.

## Reproduce locally

The recipe below builds and scans a **new** `linux/amd64` assessment artifact;
it does not guarantee byte-identical recovery of the final image digest recorded
above. The Dockerfile uses floating base tags and live APT repositories, and
even pinning the observed base digests alone would not freeze subsequent package
resolution or build metadata. Exact-image replay requires the retained artifact
at the recorded digest; later advisory-database downloads can also change scan
results. Use a clean Studio checkout of the exact reviewed PR #303 head from its
PR body, not the pre-change Studio base SHA above. Use the pinned Engine SHA above
in a separate clean checkout and Docker with a `linux/amd64` builder. Replace the
sample `STUDIO` and `ENGINE` paths with local checkout paths. Keep the output directory
**outside either repository**. The release
archive SHA-256 values above must be checked before executing the scanners. The
tool-download commands below target the macOS ARM64 assessor used here; on a
different assessor host, use the same pinned releases and verify that host's
official archive checksum. The *image* target remains `linux/amd64`.

```sh
STUDIO="/path/to/clean/EdgeForgeStudio"
ENGINE="/path/to/clean/EdgeForge"
cd "$STUDIO"
# Set this to the exact PR #303 head under review, or the merged revision
# containing its Dockerfile, report helper, and image smoke changes.
STUDIO_REV="PASTE_EXACT_REVIEWED_PR_303_HEAD_SHA"
git fetch origin refs/pull/303/head
git checkout --detach "$STUDIO_REV"
git cat-file -e "$STUDIO_REV:scripts/image_assessment_report.py"
git grep -q 'apt-get upgrade' "$STUDIO_REV" -- Dockerfile
OUT=$(mktemp -d)
test "$(git -C "$ENGINE" rev-parse HEAD)" = d8f50c0edd2d9ec27e7def512455b2881a3c97fe
mkdir -p "$OUT/tools"
gh release download v1.52.0 --repo anchore/syft \
  --pattern syft_1.52.0_darwin_arm64.tar.gz --dir "$OUT/tools"
gh release download v0.119.0 --repo anchore/grype \
  --pattern grype_0.119.0_darwin_arm64.tar.gz --dir "$OUT/tools"
gh release download v0.74.0 --repo aquasecurity/trivy \
  --pattern trivy_0.74.0_macOS-ARM64.tar.gz --dir "$OUT/tools"
printf '014d561b6d13059124155f74a6c5a9a99501f5e209313638dd884f39eb418ee6  %s\n' \
  "$OUT/tools/syft_1.52.0_darwin_arm64.tar.gz" | shasum -a 256 -c
printf '500c9b2b6c089d21481815f57a553fabbd441ec7d1e79d95e3aaf40c3bfc7e36  %s\n' \
  "$OUT/tools/grype_0.119.0_darwin_arm64.tar.gz" | shasum -a 256 -c
printf '1caada5e0e2091909357c7525d3aa76f4b660b13821bc143b190c7483e31cc11  %s\n' \
  "$OUT/tools/trivy_0.74.0_macOS-ARM64.tar.gz" | shasum -a 256 -c
tar -xzf "$OUT/tools/syft_1.52.0_darwin_arm64.tar.gz" -C "$OUT/tools" syft
tar -xzf "$OUT/tools/grype_0.119.0_darwin_arm64.tar.gz" -C "$OUT/tools" grype
tar -xzf "$OUT/tools/trivy_0.74.0_macOS-ARM64.tar.gz" -C "$OUT/tools" trivy
PATH="$OUT/tools:$PATH"
docker build --platform linux/amd64 --build-context "edgeforge_engine=$ENGINE" \
  --build-arg APP_UID=1000 --build-arg APP_GID=1000 \
  --iidfile "$OUT/image.iid" -t edgeforge-studio-assessment:local .
docker image inspect edgeforge-studio-assessment:local

# Download only public advisory databases before scanning.
trivy image --download-db-only --cache-dir "$OUT/trivy-cache"
trivy image --download-java-db-only --cache-dir "$OUT/trivy-cache"
GRYPE_DB_CACHE_DIR="$OUT/grype-db" grype db update

SYFT_CHECK_FOR_APP_UPDATE=false syft scan docker:edgeforge-studio-assessment:local \
  --platform linux/amd64 --output "syft-json=$OUT/syft.json"
SYFT_CHECK_FOR_APP_UPDATE=false syft convert "$OUT/syft.json" \
  --output "cyclonedx-json=$OUT/sbom.cdx.json"
GRYPE_DB_CACHE_DIR="$OUT/grype-db" GRYPE_DB_AUTO_UPDATE=false \
  GRYPE_CHECK_FOR_APP_UPDATE=false grype "sbom:$OUT/syft.json" \
  --output json --file "$OUT/grype.json"
trivy image --cache-dir "$OUT/trivy-cache" --image-src docker \
  --platform linux/amd64 --offline-scan --skip-db-update \
  --skip-java-db-update --skip-check-update --skip-version-check \
  --disable-telemetry --scanners vuln --format json \
  --output "$OUT/trivy.json" edgeforge-studio-assessment:local
python3.11 scripts/image_assessment_report.py --syft "$OUT/syft.json" \
  --grype "$OUT/grype.json" --trivy "$OUT/trivy.json" \
  --output "$OUT/summary.json"

EDGEFORGE_STUDIO_IMAGE_ENGINE_CONTEXT="$ENGINE" \
  python3.11 -m pytest tests/smoke/test_docker_image_launch_smoke.py -q -m smoke
```

Run the final Syft/Grype/Trivy steps a second time on the same image ID and
compare the summaries. The image smoke imports Studio, runs as UID 1000, starts
the real server without source bind mounts, and exposes only `127.0.0.1` on a
dynamic host port. It rebuilds locally and is launch-contract proof, not a
claim that the new build has the retained assessment digest. Local validation:
**2,200 passed, one skipped, 29 smoke
deselected** in the non-smoke suite; L2 **one passed**; Docker image smoke
**one passed**; report and failure-path tests **30 passed**. Required PR CI must
still pass on the final PR head. No image was pushed or signed.

**Disposition:** this bounded assessment is complete with findings. It neither
selects an acceptable risk threshold nor clears M2, and it must be repeated
against the final v5 release pairing before any image acceptance decision.
