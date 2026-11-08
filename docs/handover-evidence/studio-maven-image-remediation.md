# Studio Maven image remediation - 2026-09-27

Candidate **EF-V5-M2-STUDIO-IMAGE-MAVEN-S1, revision 1** replaces only Debian's
Maven packaging with the verified official **Apache Maven 3.9.16** distribution.
The two targeted Guava advisories are remediated in the identified candidate.
Both assessments remain **complete with findings, not image or M2 clearance**.
No residual risk is accepted, and no image was published.

## Source and artifact binding

Control source: Studio `5e966225684bfabac972f7522cc6447949df02dc` (#304 merged).
Candidate implementation: `ae16517871e37963cd13a49ac152688c802771a6`.
Both use a clean, read-only archive of Engine
`127439a54bb9e1fc787cf981490e6c33e8a45da2`, including #318. Concurrent Engine
Batch work was not consumed. The application, Python dependencies, Compose
configuration, entrypoint, UID/GID defaults and security settings are unchanged.
The original checkouts' unrelated untracked files were left alone.

One control and one candidate were built for **linux/amd64** on Docker Desktop
4.82.0 / Docker 29.6.1, using the same resolved base inputs and APP_UID/GID 1000.
The build host was arm64; this is an amd64 assessment, not multi-platform proof.
The [identity record](studio-maven-image-identities.json) contains source/recipe
hashes, base index/platform/config/layer relationships, final identities, all
report/SBOM hashes, timestamps, actual Guava coordinates, and the complete APT
delta. Evidence-only commits do not change either image's tested source files.
The proof-runner correction described below is copied into a temporary container
only; it does not enter or change the assessed image. The identity record's
`source_files_sha256` preserves the original assessment inputs, including the
original runner, separately from the corrected runner's follow-up hash.

| Identity | Control | Candidate |
| --- | --- | --- |
| Image config | `sha256:4d02e8f9884f5ad3ef1c9631e0d8f4f42b1ea34132b16cb092b028d62b4e3025` | `sha256:7c0cd3f651c91bacdbf0ca79a46da6bf9cee6d531dacaf1592c3aaefe37de088` |
| OCI index | `sha256:577c8f0f30bff093dacc1efbd611ddbe44b50ce362664a255bd151e06d3b8a74` | `sha256:c1b42cc589d667877bae2839356e96064a58bf527a1c3922e20007569a85e1fe` |
| Actual OCI amd64 manifest | `sha256:09d293f09bafb62ad68f43fb3e2470805b17807e09e9f9b7e30b76a5a63d1886` | `sha256:197465ecba5c00bbd745e90f79bef29d4a4766420394e9cd04a081418e129c76` |

Saved local OCI blobs were hash-verified: each index references the above
platform manifest, each manifest references the assessed config, and that
config's ordered uncompressed layer IDs match Syft, Grype and Trivy. Syft's
Docker-daemon adapter also supplies a **serialized Docker schema-2 manifest**;
its digest is different from the compressed OCI platform manifest. Both values
are retained separately, not conflated. The adapter's embedded config bytes
hash to the actual OCI config. The existing validator's image/ordered-layer
checks remain intact. This establishes these new artifacts independently;
#303/#304's historical manifest discrepancy remains historical/open and its
evidence was not overwritten.

Final runtime versions in both images: Python 3.11.16, Debian 12.15 Bookworm,
copied Temurin JDK 21.0.12.1+1-LTS. Maven changes from Debian 3.8.7-1 to Apache
3.9.16. APT removes 56 packages that came through Debian Maven, including its
redundant OpenJDK 17 JRE and Guava. There are **no added Debian packages and no
version changes among retained Debian packages**; Python name/version inventories
are identical. Build-essential, curl and git remain. No unrelated inventory
change is credited as Maven remediation.

## Verified installation and targeted closure

[Apache recommends Maven 3.9.16](https://maven.apache.org/download.cgi), supports
JDK 8+ for Maven 3.9, and documents its
[3.9.16 release](https://maven.apache.org/docs/3.9.16/release-notes.html).
The selected [release POM](https://github.com/apache/maven/blob/maven-3.9.16/pom.xml)
is a basis for inspection, not a substitute for the downloaded artifact.

The official binary archive's SHA-512 is committed in
[`install_apache_maven.py`](../../scripts/install_apache_maven.py) and compared
**before extraction**. It matched the official release checksum. Apache's
detached signature verified in a disposable keyring imported from its official
KEYS file, with signer fingerprint `84789D24DF77A32433CE1F079EB80E92EB2135B1`.
This records Apache key provenance and a valid signature, not an independently
established web-of-trust. No host trust store was changed. The disposable build
stage uses Python's existing downloader and retains the distribution's LICENSE
and NOTICE; no new verification tools enter the final image.

The candidate's normal UID 1000 runs `/opt/maven/bin/mvn`, reports exactly
3.9.16, uses `/opt/java/openjdk` as JAVA_HOME, and creates/writes `$HOME/.m2`.
Tests reject a mismatched checksum before installing anything, reject the wrong
archive root or missing NOTICE, and preserve executable bits and license files.

| Target | Control artifact | Candidate artifact and disposition |
| --- | --- | --- |
| CVE-2020-8908 / GHSA-5mg8-w23w-74h3 | Debian `libguava-java 31.1-1` and `/usr/share/java/guava.jar` (`31.1-jre`) | **Remediated:** old package/JAR absent; verified Maven bundles `33.6.0-jre` |
| CVE-2023-2976 / GHSA-7g45-4rm6-3mm3 | Same Debian/JRE artifacts | **Remediated:** same whole-distribution replacement, not an Android JAR substitution |

[Guava's own 32.0.0 notes](https://github.com/google/guava/releases/tag/v32.0.0)
identify both security fixes in the JRE and Android releases; they distinguish
the earlier deprecation from elimination of insecure behavior and recommend
32.0.1 for the Windows regression. The observed **33.6.0-jre** is beyond these
fixed releases. [Debian's record](https://security-tracker.debian.org/tracker/CVE-2023-2976)
still identifies Bookworm 31.1-1 as vulnerable. A scanner's Android-only fix
string is not treated as the applicable replacement for this JRE artifact.

Network-disabled final-filesystem inspection traversed `/usr`, `/opt`,
`/workspace` and `/home`, resolved JAR symlinks, and inspected Java archive
contents/POM properties. The sole archive containing Guava's `Files` class was
`/opt/maven/lib/guava-33.6.0-jre.jar`, SHA-256
`dc573e1fca4fd5454f4a5fd3d7da2df03002876a4175bafc14a95980dd7713b3`.
Syft independently identified that same version/location. No old Debian Guava,
alternate Guava JAR, or image-local Maven cache copy remained. Grype retained
the control's four package/JAR observations for the two aliases; Trivy retained
the Debian observation. Neither reported a candidate Guava alert. This is an
artifact-specific fix conclusion, not a blanket clearance of Maven/JDK code.

## Fresh local assessment

The checksum-verified tools remain Syft 1.52.0, Grype 0.119.0 and Trivy 0.74.0;
archive pins/provenance follow the [original assessment](studio-image-assessment.md).
Fresh databases were downloaded once, then updates disabled for both artifacts.
Grype DB built `2026-09-27T06:30:30Z`; Trivy vulnerability DB updated
`2026-09-28T01:11:56Z`, Java DB updated `2026-09-28T00:58:56Z`. Full metadata and
database hashes are in the identity record. Observations occurred on September
27 in America/Chicago (September 28 UTC). Only public artifact/advisory downloads
occurred; no image, private source or inventory was uploaded to a scanner.

| Observation set (overlapping, never additive) | Control | Candidate |
| --- | ---: | ---: |
| Debian / Python / Java archive inventory | 222 / 109 / 98 | 166 / 109 / 52 |
| Active Grype package/advisory matches | 1,092 | 1,013 |
| Grype CRITICAL / HIGH | 44 / 124 | 43 / 112 |
| Separately retained Grype ignored matches | 2,328 | 2,328 |
| Trivy Debian matches | 3,413 | 3,336 |
| Trivy inventory-unresolved Python alerts | 3 | 3 |
| Candidate Java archive alerts (Grype / Trivy) | n/a | 0 / 0 |

The complete sanitized [control summary](studio-maven-image-control-summary.json)
and [candidate summary](studio-maven-image-candidate-summary.json) retain component
versions, severities, fixes, high/critical IDs, ignored rules/fingerprints and
unresolved Python dispositions. Both raw sets replay through the unchanged
[`image_assessment_report.py`](../../scripts/image_assessment_report.py) to the
committed summaries byte-for-byte. No fresh scan was repeated to seek favorable
results. One initial Trivy candidate attempt failed on a cache lock while control
was scanning; it produced no report and succeeded when run serially with the
same databases. No scanner exclusion or risk disposition was added.

All untargeted findings remain **OPEN**, including kernel headers (2,328 Grype
ignored matches are not accepted risk), Python interpreter advisories, pip's
embedded msgpack/pkg_resources alerts, and remaining OS/tooling families. The
candidate's Trivy results are Debian, Python and a Java result with zero alerts;
the validator still rejects unsupported result types containing vulnerabilities.
OS and standalone Python inventories reconcile across scanners. Java archive
and copied-JDK detection is not exhaustive vulnerability/applicability coverage;
an absent JDK alert is not JDK clearance. No introduced Maven dependency alert
was observed in these database snapshots. No-fix/vendor-won't-fix states remain
open, not accepted. The earlier [ranked triage](studio-image-triage.md) remains
historical; this record closes only its two targeted Guava identities for the
new candidate, not every finding that disappeared with Debian Maven dependencies.

## Compatibility and regression proof

The mount-free, non-root image smoke executed against the assessed candidate:
**1 passed**, importing Studio and starting its default server with loopback-only
dynamic host publication. The task-owned proof container also had no mounts.
[`maven_image_build_run_proof.py`](../../scripts/maven_image_build_run_proof.py)
used real `/project/open`, `/export/write`, `/export/generate`, `/export/build`,
`/export/run`, managed HTTP proxy, and `/export/stop` routes, not mocked adapters.
Every case exported/generated with zero warnings, ran `mvn -B -ntp clean verify`
with one test, zero failures/errors/skips, then ran Studio's unchanged
`mvn clean package -DskipTests` packaging command and observed HTTP 200 / health UP.

| Synthetic case | Generated compiler target | Image runtime | Outcome |
| --- | --- | --- | --- |
| HC legacy / Boot 3.3.5 | Java 17, class-file major 61 | Temurin 21 | Tests, package, startup, HTTP passed |
| HC jobless preview / Boot 4.1.1 | Java 17 | Temurin 21 | Tests, package, startup, HTTP passed |
| FS jobless enterprise / Boot 3.3.5 | Java 21, class-file major 65 | Temurin 21 | Tests, package, startup, HTTP passed |

The jobless variants remove file/staging handoffs and downstream file contracts
**only in temporary input**. An initial HC preview attempt correctly rejected
its Batch-requiring handoff. The FS enterprise test initially lacked required
PostgreSQL credentials; it passed with a task-owned synthetic PostgreSQL 16
fixture on a private Docker network, with no published database port. Neither
failure prompted product/profile/Engine changes. No Batch/Kafka or M5a proof is
claimed. KA stayed OFF; no KS invocation occurred.

The same verified distribution was also used outside the final image: available
Temurin 17.0.18 on macOS passed the generated legacy app's `clean verify`; available
Homebrew JDK 21.0.12.1 passed the jobless preview's `clean verify`. Each executed
one test with zero failures/errors/skips. No host JDK/Maven was installed globally.
Java-release-17 compilation inside the image does **not** imply a JDK 17 runtime
there. These representative checks do not certify every Maven plugin or profile.

Focused installer/reporting/Build & Run/Docker/default checks: **70 passed**.
Normal non-smoke suite with the frozen Engine input: **2,211 passed, 29 deselected**.
L2 in-process smoke: **1 passed**. The established strict Python audit found no
known vulnerabilities. Ruff passed for changed Python files; the full advisory
lint retains one pre-existing import-order finding in `tests/test_readiness_view.py`,
which is unchanged by this PR. `git diff --check` passed. Required PR checks must
be green at the PR's exact reported head; final CI status belongs in the PR body.
An initial secret scan mistook a Debian package name under a generic JSON `key`
field for an API key. The evidence now uses explicit `name`/`version` fields;
gitleaks 8.30.1 passes without any scanner rule, allowlist or suppression change.

### Proof-runner review correction - 2026-09-28

The [independent review](https://github.com/santosh-sh/EdgeForgeStudio/pull/305#pullrequestreview-5334009449)
at `b3563dd0a304802c2a4b3d0d9c4e1558ecf41c32` reproduced a false passing
result for an all-skipped Surefire report. Surefire's `tests` count includes
skipped cases. The runner now requires `tests - skipped > 0`, zero skips and
zero failures/errors **before packaging or recording a passing result**. This
gate uses an explicit exception, not an assertion that Python optimization can
disable. Missing/empty reports and incomplete/negative counters also fail closed.
The submitted historical runs did execute one test each with zero skips; this
correction does not recast those observations as failures or replace their hashes.

New controlled `execute()` regressions cover all-skipped, partially skipped,
skips across multiple reports, missing/empty reports, failures, errors, invalid
counters, and successful single/multiple zero-skip reports: **11 passed**, also
**11 passed** with `python -O` (its expected assertions-disabled warning).
Focused runner/installer/reporting/Build & Run/defaults: **81 passed**. Full
non-smoke suite with the same frozen Engine: **2,222 passed, 29 deselected**, no
skips. L2 and the exact retained-image mount-free/non-root startup smoke each
passed one test. Changed-file Ruff and diff hygiene passed.

The corrected runner was copied into a mount-free UID-1000 container of the
**same assessed candidate**, without a rebuild, dependency change or new scan.
Follow-up Boot 3 legacy and jobless Boot 4.1 preview runs each executed one Maven
test with zero failures/errors/skips, then packaged and reached HTTP 200 / health
UP through the real Studio routes. Follow-up hashes are recorded separately in
the identity record; raw outputs remain temporary. The Java-21/PostgreSQL and
host-JDK results above are retained original evidence, **not rerun in this
correction**. No new compatibility or whole-image clearance is claimed.

### Historical image capability clarification - 2026-09-30

The [independent review of #305](https://github.com/santosh-sh/EdgeForgeStudio/pull/305#issuecomment-5883816589)
observed that the candidate lost Java font rendering when Debian Maven's
OpenJDK 17 dependency chain (including fontconfig and font packages) was removed.
The reviewer observed headless Java font measurement succeed in the historical
control image and fail in the candidate. Supported generation/build/run proof
above passed, but adopter code that renders or measures text may need an
explicitly extended, assessed image. This is a disclosure of that reviewed
observation, **not** a new font experiment or a decision to restore packages.

The prebuilt-mode image smoke skips the Dockerfile build and checks only its
named image. Historical #305 smoke proof is bound to the recorded candidate
identity, not to future source or Engine revisions. A fresh source/recipe claim
needs an identified new build; neither the historical digest nor its scan is
relabelled as current-pair evidence.

## Reproduction and replay

Use a clean checkout of the current PR head for the corrected proof runner;
the implementation commit above binds the original image, not this later guard.
Set task-local `OUT`, verified `TOOLS`, and read-only
`ENGINE_REPO`; no host-specific path is part of committed evidence. Export Engine
with `git archive 127439a54bb9e1fc787cf981490e6c33e8a45da2`, not its moving branch.
For controlled builds, replace FROM tags in temporary recipes with the two base
index digests in the identity JSON and use those same recipes for both builds.

```bash
docker build --platform linux/amd64 \
  --build-context edgeforge_engine="$OUT/engine" \
  --build-arg APP_UID=1000 --build-arg APP_GID=1000 \
  --metadata-file "$OUT/candidate-build.json" \
  -f "$OUT/candidate.Dockerfile" -t "$CANDIDATE_TAG" .
# Control: clean Studio 5e966225 archive, its original Dockerfile with the same
# FROM digest substitutions, same Engine context, platform and UID/GID args.

"$TOOLS/syft" "docker:$CANDIDATE_TAG" \
  -o "syft-json=$OUT/candidate-syft.json" -o "cyclonedx-json=$OUT/candidate-sbom.json"
GRYPE_DB_CACHE_DIR="$OUT/grype-db" GRYPE_DB_AUTO_UPDATE=false \
  "$TOOLS/grype" "sbom:$OUT/candidate-syft.json" -o json > "$OUT/candidate-grype.json"
"$TOOLS/trivy" image --image-src docker --offline-scan --skip-db-update \
  --skip-java-db-update --skip-check-update --disable-telemetry --scanners vuln \
  --list-all-pkgs --format json --cache-dir "$OUT/trivy-cache" \
  --output "$OUT/candidate-trivy.json" "$CANDIDATE_TAG"
python3.11 scripts/image_assessment_report.py \
  --syft "$OUT/candidate-syft.json" --grype "$OUT/candidate-grype.json" \
  --trivy "$OUT/candidate-trivy.json" --output "$OUT/candidate-summary.json"
cmp "$OUT/candidate-summary.json" docs/handover-evidence/studio-maven-image-candidate-summary.json
# Replay the retained control reports analogously. Check input hashes first.
```

Fresh reproduction builds a **new** artifact: digest-pinned bases alone do not
freeze live APT package resolution, build timestamps, or later advisories. Do not
expect recovery of the assessed image digest or byte-identical new scan reports.
The `cmp` above is for **retained report replay**, not a promise for a future scan.
Keep downloaded DB snapshots unchanged across control/candidate and serialize
Trivy scans using one cache. Validate new identities before interpreting deltas.

For live proof, copy the runner and synthetic HC/FS project JSON into a fresh
task-owned candidate container; set `PYTHONPATH=/workspace/EdgeForgeStudio`,
`EDGEFORGE_STUDIO_ENGINE_TRANSPORT=cli`, and a writable Docker output root through
`EDGEFORGE_STUDIO_DEFAULT_OUTPUT_PATH`. Invoke the runner with `--project`,
`--profile`, `--proof-root` and `--run`; add `--jobless` for the preview and FS
enterprise cases. Enterprise requires its documented synthetic PostgreSQL
environment. Do not mount source, mutate committed samples, or enrich the image
before scanning. All generated apps, Maven outputs, raw scans, OCI images and
caches stay under task-local temporary storage; task containers/network are
removed after proof, without global Docker pruning.

Final v5 acceptance still requires a separately scheduled rebuild/reassessment
against the selected Studio/Engine release pair, plus independent residual-risk
and signing decisions. This draft PR does not wait for or authorize that clearance.
