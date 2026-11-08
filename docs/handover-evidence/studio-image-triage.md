# Studio image findings triage - 2026-09-26

**Status: complete triage deliverable with open findings, not M2 clearance.** This
reuses the local, retained `linux/amd64` assessment from [Studio PR #303](https://github.com/santosh-sh/EdgeForgeStudio/pull/303).
No image was rebuilt, rescanned, published, or changed. No scanner exclusion is
a maintainer risk decision. A final selected Studio/Engine release pair still
needs its own image rebuild, reassessment, and disposition decision. The
[original assessment](studio-image-assessment.md) and
[original sanitized summary](studio-image-assessment-summary.json) remain unchanged.

## Evidence and reconciliation

| Item | Retained identity or observation |
|---|---|
| Studio source now reviewed | `main @ beb8e0ef66143229d4e807040187d8a4905eedb5` (merged #303); the assessed Dockerfile change came from `fab11953b8a0eadb602419c362b1943bfd22d0a1`, while #303's final evidence correction was `cd447d723ee631b8e17722b450d7fd2b119c4fcb` |
| Engine input for the assessed image | `d8f50c0edd2d9ec27e7def512455b2881a3c97fe`, not current Engine main |
| Image | local image/index `sha256:f571cc7702cc700fe5ae8d5ce26f94636f5bf4a3dddfcac65185a31214c5eee8`; config `sha256:1b51c45fab81838070f0c803295f259b06c647350e41074d56078905463052c1`; `linux/amd64`, non-root `appuser` |
| Scanner metadata | Syft `1.52.0`; Grype `0.119.0`, DB schema `v6.1.9` built `2026-09-23T06:31:39Z`; Trivy `0.74.0`, DB updated `2026-09-23T12:53:55Z`, Java DB updated `2026-09-19T01:01:52Z` |
| Round 1 observation | Grype `2026-09-23T15:11:50-05:00`; Trivy `2026-09-23T15:12:09-05:00` |
| Round 2 observation | Grype `2026-09-23T15:12:58-05:00`; Trivy `2026-09-23T15:13:07-05:00` |
| Coverage | Syft: 222 Debian packages, 109 installed Python distributions, 98 Java archives, copied Temurin JDK `21.0.12+8-LTS`; Trivy: Debian/Python results only. Native/embedded code and JDK advisory coverage remain limited as described in the original assessment. |

| Retained report | Round 1 SHA-256 | Round 2 SHA-256 |
|---|---|---|
| `final-syft-N.json` | `4a48a3cbd8fae942d5154e8d537db9f3229bdb40acedee53ad1440e59f3cc7ce` | `528b17079ba960c28d099f5aa0833779863941e03f0280dd919cbb3abeeb99eb` |
| `final-grype-N.json` | `10a99d182884b726e8cc900f64599ff513f6e4b1d36e21cab0b69d6f66fc21` | `19d0e5bcacfb0a3b281ff5ccebf885f09810ff39b413cb3a6debca12a957a7e3` |
| `final-trivy-N.json` | `3ebaf2cae2444cb95b6197ef64bb7e0aca934786e1088e5b3eee86a74631e063` | `68a5725f8f80e0530088cea9822a5a8b215c404832e9949a33b7d93af405cc50` |
| `final-sbom.cdx.json` | `d266dcbf61655930e0d03d17cadc84b285ec769d14872c6960a0301c23acc3c6` | one retained SBOM |

Both rounds passed the [existing report validator](../../scripts/image_assessment_report.py)
and reproduced `studio-image-assessment-summary.json` byte-for-byte. They also
produced identical ledger components, observations and groups after excluding
only the deliberately different input hashes. The
[sanitized normalized ledger](studio-image-findings-ledger.json) contains 6,072
source observations across 106 affected component identities and 3,048
component/advisory groups:

| Scanner result array | Observations | Meaning |
|---|---:|---|
| Grype active | 1,100 | Package/advisory matches, not proven exploit paths |
| Grype ignored | 1,938 | Rule-excluded matches, still open |
| Trivy Debian | 3,031 | Separate feed; overlaps Grype |
| Trivy Python | 3 | Imported-SBOM alerts with unresolved embedded-code inventory |

The ledger indexes each source array from zero, retains scanner status,
component/version, observed advisory ID and explicit aliases, severity, fix
metadata and applied ignore rule. A group merges only the same package
type/name/version and an exact ID or an explicit unambiguous CVE alias. Its
observation indexes reverse to source report, result and position. Distinct
package identities (including the Debian Guava package versus its JAR) and
unproven alias links remain separate. Every group defaults to
`open/unassessed`; this ledger is not a risk-disposition file. Scanner totals
are **not additive**. Fix metadata `fixed`, `not-fixed`, or `wont-fix` is a
scanner/vendor statement, not proof of remediation, absence, or acceptance.

Syft and Grype report a platform manifest digest
`sha256:2403997ec643736849203042867766bd9cebbfe8e22d0d357887da5e0bd16c5c`.
The earlier #303 prose recorded a different platform-manifest digest
`sha256:2430bfbddb83886cda1af8e81985d67b4a3e38b9ae822b1eddf709e246e6807e`.
Their config, index and layer identities agree with Trivy and the retained
local image, but this manifest-text discrepancy is **not** silently resolved;
reconcile it from the retained OCI artifact before citing either platform
manifest as release-pair proof.

## Four bounded investigations

### 1. Kernel userspace headers

**Classification: open/unassessed, not scanner-cleared.** The exact image's
package database reports `linux-libc-dev 6.1.187-1` installed; its file list
contains `/usr/include/linux` and architecture headers. [Debian describes](https://packages.debian.org/bookworm/linux-libc-dev)
this as userspace development headers, not the container's running host kernel.
[Grype v0.119.0](https://github.com/anchore/grype/blob/v0.119.0/cmd/grype/cli/commands/root.go#L106-L138)
applies its default `exact-indirect-match` exclusion for `linux-libc-dev`
matched through the `linux` upstream source. The retained rule accounts for
1,938 ignored matches (125 Critical, 650 High); Trivy reports 1,939 matches
against the same installed package. Exactly 1,938 advisory IDs coincide;
Trivy's additional `TEMP-0000000-F7A20F` remains a separate observation.
The kernel-CVE match does not demonstrate a vulnerable kernel running *inside*
the container, but header/package presence also does not support a blanket
not-affected conclusion. Next: review whether any advisory concerns shipped
userspace headers or build products, and assess whether a separately scoped
image change can remove development headers without breaking supported builds.

### 2. Imported-SBOM Python alerts

**Classification: open/unassessed; no automatic not-installed or not-affected
disposition.** Trivy's imported SBOM identifies `msgpack 1.1.2` (HIGH,
`GHSA-6v7p-g79w-8964`) and `setuptools 70.3.0` (HIGH
`CVE-2025-47273`, MEDIUM `CVE-2026-59890`). Neither version is a standalone
distribution in Syft's installed-Python list. However, a read-only,
network-disabled inspection of the exact image found pip `26.2.1` with
`pip._vendor.msgpack` 1.1.2 and `pip._vendor.pkg_resources`; pip's `vendor.txt`
names setuptools 70.3.0, while standalone setuptools is 83.0.0.

The image selects `pip._vendor.msgpack.fallback` and has no vendored msgpack
native `.so`; the [upstream msgpack advisory](https://github.com/msgpack/msgpack-python/security/advisories/GHSA-6v7p-g79w-8964)
and [1.2.1 changelog](https://github.com/msgpack/msgpack-python/blob/main/CHANGELOG.md#121)
describe a native unpacker fault. The image contains vendored `pkg_resources`
but no `package_index.py` or `filelist.py` in pip's vendor tree; the
[PackageIndex advisory](https://github.com/pypa/setuptools/security/advisories/GHSA-5rjg-fvgr-3xxf)
and [FileList advisory](https://github.com/pypa/setuptools/security/advisories/GHSA-h35f-9h28-mq5c)
name those surfaces. This narrows plausible applicability, but code/file
presence alone does not prove reachability or non-reachability. Next: bind
each advisory to the actual vendored code and image use path, verify the
absence of an alternate vulnerable copy, and seek independent review before
any supported not-affected conclusion. A future pip/vendor update is a
separate, tested fix candidate, not a remediation recorded here.

Image-internal file hashes: `pip/_vendor/msgpack/fallback.py`
`d20d4fce9d2fb66044989e70f45decffe24c55444ff114b81b571ce5345a02c2`;
`pip/_vendor/pkg_resources/__init__.py` `bdb4c9d3faee5201b1423944aacaee16688d3d5ca1dadf6afb3c930d3d39df12`;
`pip/_vendor/vendor.txt` `3df0c9601bfa2e0dca23cc574a4f900a4d7fdad060ab203fab8354350ed93320`.

### 3. Python interpreter

**Classification: open/unassessed; a Python-line move is decision required.**
The exact image and Syft identify `/usr/local/bin/python3.11` at `3.11.16`.
Grype has 12 binary findings, ten with scanner-listed fixes only on newer
Python 3 **minor/feature** lines (`3.13`, `3.14`, `3.15`) and two without a
listed fix. The ten IDs and their exact fix versions are in the ledger;
the HIGH `CVE-2026-82049` is among them. The [PSF 3.11.16 release record](https://www.python.org/downloads/release/python-31116/)
shows 3.11 receives irregular security-only source releases through October
2027. The [CPython tarfile issue](https://github.com/python/cpython/issues/157190)
still lists 3.11 as affected and shows backport work for other branches, not
a released 3.11 correction for `CVE-2026-82049`. No scanner-listed 3.11 fix
is not proof that a future backport cannot arrive. Next: check PSF advisories,
the 3.11 branch and base-image updates per listed ID; test a compatible 3.11
backport if one lands. If only another Python 3 line resolves material findings,
seek a separate compatibility/design decision and run the full Studio/Engine
image proof. Do not treat a scanner `fixed` state as fixed in this image.

### 4. Guava in the Maven-capable final image

**Classification: fix candidate with packaging decision required; not
remediated.** The exact image has Debian `libguava-java 31.1-1` and its
`/usr/share/java/guava.jar` reports `31.1.0.jre` and hashes to
`1d4ca0e3ee66921e8cb6521b62ecce32cc62abad391bf70b2fd14d40e7681f3a`;
relevant I/O classes are present. Grype's JAR observations are
[`GHSA-5mg8-w23w-74h3`](https://github.com/advisories/GHSA-5mg8-w23w-74h3) /
`CVE-2020-8908` and
[`GHSA-7g45-4rm6-3mm3`](https://github.com/advisories/GHSA-7g45-4rm6-3mm3) /
`CVE-2023-2976`. The same CVEs appear for the
Debian package, but the ledger keeps the package and JAR artifact identities
separate. [Guava's release policy](https://github.com/google/guava/wiki/ReleasePolicy)
distinguishes JRE and Android artifacts. The latter advisory's `32.0.0-android`
version boundary is **not** an instruction to replace the installed JRE
artifact with an Android JAR. [Debian's tracker for CVE-2023-2976](https://security-tracker.debian.org/tracker/CVE-2023-2976)
marks Bookworm `31.1-1` vulnerable and a newer-suite `32.0.1-1` fixed;
[CVE-2020-8908](https://security-tracker.debian.org/tracker/CVE-2020-8908)
remains vulnerable but marked ignored for Bookworm's policy. Neither vendor
status is Studio risk acceptance. Next: evaluate a supported Debian/JRE
package or Maven-tooling change against Build & Run, classpath and Java 17/21
proof; do not swap flavors, remove Maven, or edit the Dockerfile in this PR.

## Ranked remaining queue and decision packages

All high/critical observations outside the four groups above remain visible
in the ledger with exact advisory IDs and fix metadata. The following bounded
queue groups **affected installed identities**, not severities added across
feeds. For these Debian rows neither retained feed lists a compatible fixed
Bookworm version; verify each source advisory in Debian's tracker before a
future remediation or not-affected decision.

| Rank | Open family and exact installed binary-package identities | Next investigation |
|---|---|---|
| 1 | `curl`, `libcurl3-gnutls`, `libcurl4` (`7.88.1-10+deb12u15`) | Map 13 distinct high/critical Grype IDs to Debian Bookworm status and Studio's outbound-fetch/build use; check same-distribution updates first. |
| 2 | `libssl3`, `openssl` (`3.0.20-1~deb12u2`); `libsqlite3-0` (`3.40.1-2+deb12u2`); `libexpat1` (`2.5.0-1+deb12u3`); `libglib2.0-0` (`2.74.6-2+deb12u9`); `zlib1g` (`1:1.2.13.dfsg-1`); `libtasn1-6` (`4.19.0-2+deb12u1`) | Resolve affected runtime paths and Debian backports; do not infer non-applicability from build-tool orientation. |
| 3 | `libc-bin`, `libc-dev-bin`, `libc6`, `libc6-dev` (`2.36-9+deb12u14`); `libsystemd0`, `libudev1` (`252.39-1~deb12u2`) | Check source-package advisories, fixed Bookworm versions and final-image reachability separately. |
| 4 | `perl`, `perl-base`, `perl-modules-5.36`, `libperl5.36` (`5.36.0-7+deb12u3`); `bsdutils`, `libblkid1`, `libmount1`, `libsmartcols1`, `libuuid1`, `mount`, `util-linux`, `util-linux-extra` (util-linux `2.38.1-5+deb12u3`) | Separate required runtime tools from Maven/build-time tools; test any removal or package update against image startup and supported Build & Run. |
| 5 | `libncursesw6`, `libtinfo6`, `ncurses-base`, `ncurses-bin` (`6.4-4`); `gzip` (`1.12-1`); `libacl1` (`2.3.1-3`); `libcups2` (`2.4.2-3+deb12u9`); `libharfbuzz0b` (`6.0.0+dfsg-3`); `libldap-2.5-0` (`2.5.13+dfsg-5`); `libplexus-utils2-java` (`3.4.2-1`) | Check each remaining high/critical identity against vendor advisories and classpath or executable use; keep unassessed items open. |

These ranks order investigation, not prove exploitability. The most bounded
follow-ups are separate product-remediation proposals, not changes in this PR:

| Order | Bounded package and likely Studio files | Compatibility decision and proof |
|---|---|---|
| 1 | Same-Bookworm OS package refresh when a vendor fix exists; `Dockerfile` and image-assessment evidence only if the build recipe needs to change | Confirm the fixed Debian package is available for the selected release pair. Rebuild and rescan; prove non-root mount-free startup, image smoke, strict Python audit, Studio tests and Build & Run. Do not infer a fix from a new scan date alone. |
| 2 | pip/vendored-code update if an applicable embedded alert remains; `constraints.txt`, relevant dependency evidence and tests | Bind each advisory to the embedded artifact first. Prove the selected pip wheel changes that code, all package-policy checks pass and the assessed image actually contains the corrected vendor copy. |
| 3 | Python 3 feature-line, Debian distribution, copied JDK or Maven-packaging change; `Dockerfile`, dependency controls, deployment guidance and assessment tests | Requires an explicit compatibility/design decision before implementation. Prove supported Python/Java behavior, Maven Build & Run, Studio/Engine pairing, security defaults and complete image reassessment. |

No-fix and vendor-won't-fix matches remain open until advisory-specific
applicability evidence or a maintainer decision names scope, owner, rationale,
mitigation and review trigger. None is accepted here. The separate final
Studio/Engine release-pair assessment is also a maintainer scheduling decision.

## Reproduce and hand off

Keep the raw reports outside the repository. From a clean Studio checkout
containing the merged #303 validator and this ledger helper, set `REPORTS` to
the local retained report directory and `OUT` to a temporary directory:

```sh
python3.11 scripts/image_assessment_report.py \
  --syft "$REPORTS/final-syft-1.json" --grype "$REPORTS/final-grype-1.json" \
  --trivy "$REPORTS/final-trivy-1.json" --output "$OUT/summary-1.json"
python3.11 -m scripts.image_findings_ledger \
  --syft "$REPORTS/final-syft-1.json" --grype "$REPORTS/final-grype-1.json" \
  --trivy "$REPORTS/final-trivy-1.json" --output "$OUT/ledger-1.json"
cmp docs/handover-evidence/studio-image-assessment-summary.json "$OUT/summary-1.json"
cmp docs/handover-evidence/studio-image-findings-ledger.json "$OUT/ledger-1.json"
```

Use `-2` report names for round 2; its normalized components, observations,
groups and rules match round 1, while `source_sha256` properly differs. The
helper reads only local files and does no scanning or network access.
Raw reports, caches, source trees and image layers remain uncommitted. Final
M2 clearance still requires complete release-pair coverage, evidence-backed
dispositions for these open identities, and any required maintainer decisions
under the [Engine M2 proposal](https://github.com/santosh-sh/EdgeForge/blob/main/docs/v5-release-readiness.md).
