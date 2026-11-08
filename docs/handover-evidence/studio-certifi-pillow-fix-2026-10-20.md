# Certifi/Pillow correction and bounded image proof — 2026-10-20

Candidate **EF-V5-M2-STUDIO-CERTIFI-PILLOW-FIX-S1 rev1**. Corrects the nine
standalone dependency matches that failed the [preserved CI run](https://github.com/santosh-sh/EdgeForgeStudio/actions/runs/39498938191).
The [machine record](studio-certifi-pillow-fix-2026-10-20.json) binds primary
responses, installed graphs, copy boundaries, OCI identities and private report
hashes. This is a bounded correction, not M2, whole-image or release acceptance.

## Selection and compatibility

Only two of the **95 reference pins** change: `certifi==2026.6.17` to
`2026.10.19`, and `pillow==12.3.0` to `13.0.0`. Requirements, optional extras,
Python **>=3.11**, packaging tools and Dockerfile policy remain unchanged.

[Certifi's primary advisory](https://github.com/certifi/python-certifi/security/advisories/GHSA-6q48-6c7w-9gw2)
explains the compromised emSign ECC Root CA G3 chain. The initial October 18
security release removed all emSign roots; October 19 restored unaffected roots.
The [Python security announcement](https://discuss.python.org/t/information-for-python-users-regarding-emudhra-emsign-ca-certificate-security-incident/109576)
recommends October 19 for compatibility. The imported standalone bundle excludes
G3 and retains the three unaffected emSign roots. No distrusted root is restored
by this change, and TLS verification remains enabled.

[Pillow 13 release/migration notes](https://pillow.readthedocs.io/en/stable/releasenotes/13.0.0.html)
and its [Python support table](https://pillow.readthedocs.io/en/stable/installation/python-support.html)
retain Python 3.11. [Official package metadata](https://pypi.org/pypi/pillow/13.0.0/json)
requires `>=3.11`; official host cp 311/macOS ARM 64 and image cp 313/manylinux AMD64
wheels were downloaded, SHA-256 verified and compared with installed members.
The observed official 12.x release list ends at vulnerable 12.3.0: no published
maintained 12.x correction was available. Removed APIs (I-mode PNG clipping,
fromarray dtype override, get_child_images placement, Image._show, obsolete CMS
properties and Makernote spelling) have no Studio source caller. The exercised
pdfplumber/openpyxl consumers use supported RGB/load/save/draw paths.
No source build, compatibility patch or feature removal was needed.

| Standalone finding | Tested correction |
| --- | --- |
| GHSA-6q48-6c7w-9gw2 (certifi) | 2026.10.19 |
| GHSA-p4wg-p73j-c528 (Pillow PDF) | 13.0.0 |
| GHSA-65qm-jvmh-6pqg (GIF) | 13.0.0 |
| GHSA-58r4-6rv3-gfh8 (morphology) | 13.0.0 |
| GHSA-pchr-8j38-3x4p (TIFF encode) | 13.0.0 |
| GHSA-q45j-58j2-45rg (TIFF decode) | 13.0.0 |
| GHSA-462x-pgg6-55fp (TIFF tiles) | 13.0.0 |
| GHSA-c6hw-5grf-ff96 (TIFF tiles/RGBA) | 13.0.0 |
| GHSA-vx6w-vv9f-6gvg (EPS) | 13.0.0 |

Primary affected/fixed ranges, aliases, retrieval dates and exact response hashes
are in the machine record. These are package corrections and benign compatibility
checks, not proof that every vulnerable operation was reachable or an exploit
corpus replay. The baseline strict audit reproduced exactly nine matches once;
corrected complete reference and actual image graphs passed strict audit with
zero findings and zero omitted packages. Existing CI enforcement is unchanged.

## Consumers and executed proof

The resolved graph includes `httpx/httpcore -> certifi` and
`pdfplumber -> Pillow`; pdfminer.six declares Pillow under its optional `image` extra. Studio's export runtime uses HTTPX
AsyncClient; Engine/FastMCP clients also depend on HTTPX. Guarded OpenAPI fetching
uses the standard HTTPSConnection trust path, not an implicit certifi override.
HTTPX2, used by TestClient, uses platform truststore. Both default client contexts,
the asynchronous runtime client and guarded HTTPS context retain CERT_REQUIRED
and hostname checks. No external handshake or production content was used.

Studio declares document helpers for its supported runtime surface; it does not
call Pillow directly. Knowledge uploads are forwarded to KS through the existing
adapter, so these checks do not claim a live KS ingestion run or alter KA-OFF.
Synthetic checks exercise PNG/JPEG/TIFF/GIF, PDF creation and pdfplumber rendering,
image-bearing XLSX and DOCX round trips, and malformed image/PDF rejection.
These close prior behavior-coverage gaps without changing application behavior.

| Check | Result |
| --- | --- |
| Clean actual host Python 3.11.15 constrained install/toolchain/pip check | PASS |
| Normal host suite | 2506 passed, 45 skipped, 32 deselected |
| Host L2 | 1 passed |
| Final affected host selection | 76 passed |
| Actual Python 3.13.16 image imports/pip check/affected callers | 9 caller cases passed |
| Existing mount-free non-root image launch smoke | 1 passed, UID 1000 |
| Complete strict audits | 95 host/reference pins; 94 actual image packages, zero findings/omissions |
| Existing assessment/ledger and OCI integrity reducers | PASS |

The reference SBOM, licenses, constrained freeze and audit match exactly across
all 95 names/versions. Image markers omit backports.tarfile/importlib_metadata/zipp
and include existing Linux keyring dependencies jeepney 0.9.0 and SecretStorage
3.5.0. These are all included in its strict audit, with no version drift for shared
packages. All seven certifi members match its official wheel in both environments;
132 Pillow package/native members match each platform's official wheel.

## Actual image and copy boundaries

| Identity | Value |
| --- | --- |
| Image-tested Studio code | `529ec2d113fb619b2db94dacd0a541809c3818ce` |
| Merged Engine snapshot (origin/main at entry) | `ca53afb40ac9ba67d74f9d27c2d52e63b909970c` |
| OCI index/local artifact | `sha256:ade363aed9b85edc8e493bf1f62745fe501c95116ecb7569571a4c1a4022206c` |
| AMD 64 platform manifest | `sha256:29db810e476c3e0aac31b5fcf5583e59555f3cbbc0ed7142b670d624d34d2ca3` |
| Configuration | `sha256:73d2cdd1cdf7b47cc9c27f4c4511e3c7fdbbc038fec776771a1e0232a4d0794b` |

One fresh Dockerfile dependency image, **zero corrective rebuilds**, named Engine
context from a fixed merged archive. Python 3.13.16 slim Bookworm and Temurin21
index pins, Maven named stage and runtime policy are unchanged. BuildKit reused
unchanged base/JDK/Maven/APT cache layers; it did not re-resolve APT. Shared prefix
layers 0–8 match the prior actual image. Current final-image scans assess this
new artifact; no new whole-stage assessment is claimed. Packaged Studio/Engine
files match their frozen source bytes. Later changes affect tests/evidence only;
the delivery/review head is recorded separately and must not relabel the image.

The current Pillow wheel changes all eight native extension bytes. Its bundled
libjpeg-turbo becomes 3.2.0 and libtiff 4.7.2; version/byte/linkage records retain
all 18 bundled libraries. Same version strings do not imply same native bytes or
clearance. Optional Tk remains absent; no fonts/system packages were installed.

**Standalone certifi does not fix active pip or ensurepip.** Active pip26.2.1
still vendors certifi2026.06.17; the independent ensurepip pip26.2.1 wheel contains
the same old bundle. Both hash to
`bbc7e9c01d7551bb8a159b5dedd989b8ee3ce105aff522b68eb1b01bf854cab0`
and still include G3: **OPEN**. The corrected standalone bundle hashes to
`50f79f98dac192b20dbf73f35c56f0b0c557ab267ff5199d1117cc1180b70785`.
No pip-private tree or bootstrap seed was changed; private urllib3 remains OPEN.
Strict standalone-audit silence never clears these embedded copies.

## Current scan observations and limits

Verified Syft1.52.0, Grype0.119.0 and Trivy0.74.0 ran locally; public databases
were downloaded once and frozen. No source, image or inventory was uploaded to an
advisory service. Current Grype DB is v6.1.10 built 2026-10-20T06:29:49Z; exact
binary/database hashes and Trivy metadata are in the record/private packet.

The lossless ledger retains **3840 groups / 7663 observations**: Grype 1050 active
plus 2775 ignored, Trivy 3831 Debian plus7 unresolved Python observations.
These overlap and are not unique vulnerability counts. Compared with the committed
October 14 ledger:3527 groups persist,313 are newly observed,1 is now silent.
Every new observation is retained privately with component/advisory identity,
source indexes and a conservative **OPEN** disposition.

The 313 new groups comprise linux-libc-dev 305; libtirpc3/dev/common2 each;
ca-certificates1; embedded certifi1. The 312 OS groups join unchanged inherited
versions, package-file manifests and original payload layers. They are new DB
matches rather than introduced/worsened component content, and do not block the
complete standalone strict audit or demand an expansion to establish this bounded
correction. Header metadata does not describe the Docker host kernel; libtirpc
caller applicability remains unproved. The separate OS trust-store DLA-4845-1
remains OPEN, as does pip-private/seed certifi. Broader image remediation requires
a separate authorization; no inherited-family name alone is used as clearance.
The now-silent linux-libc-dev CVE-2026-89603 retains its historical unresolved
state. Historical native/transient/caller gaps and old dispositions keep their
original artifact/database identities; none is silently renewed.

Private retention: **Studio-Certifi-Pillow-Fix-2026-10-20** under the established
maintainer artifact convention. The committed JSON carries selected raw hashes;
a separate final review-input manifest binds exact committed bytes and private
inputs without a self-referential seal. A clean clone can rerun setup, tests,
generation, strict audits and the recipe; exact historical artifact/database
replay requires the private packet. No full M2/generated-app campaign, Suite L5,
other-platform proof, release, risk acceptance or parked-PR 318 resume occurred.

All executed failures/recoveries are retained: sandbox DNS; documentation403
replaced with tagged RST; two incorrect new-test assumptions corrected;
pre-copy Trivy tool path failure before scan; warning-prefixed JSON extraction
and resulting missing-inventory audit input corrected; ledger invoked as module
rather than direct file. No unchanged failing advisory/build retry occurred.
Allowances: baseline audit1/1, selected correction1/1, pre-review repairs2/2,
initial image build1/1, corrective rebuild0/1. Independent review/CI outcomes are
recorded against their exact delivery head separately. Skips are not passes.
