# Authlib and dnspython audit correction - 2026-10-28

**EF-V5-STUDIO-AUDIT-CORRECTION-S1 revision 1.** Updates existing draft
[PR #321](https://github.com/santosh-sh/EdgeForgeStudio/pull/321), preserving
project-intent commit `e7cfc96c545db89a9ef76123d95c782696a8d1d4` and base main
`ecd66fefc19593719d6f6da2b7c950aacfb8d54b`. README, CONTRIBUTING and publication
preparation remain byte-identical to that intent commit. Its Apache-2.0/DCO,
commercial-use permissions, no paid/custom/managed service or guaranteed support,
adopter responsibilities and mandatory publication gates are not rewritten.

The [compact receipt](studio-audit-correction-2026-10-28.json) binds source,
artifact/advisory hashes, exact execution times, graph coverage and private log
hashes. Local checks ran against the appended working tree; relevant source-file
hashes identify their input. Final-head CI and independent review are recorded
separately in the PR. This is not release authorization or M2 clearance.

## Original observations and selected corrections

The retained [failed CI job](https://github.com/santosh-sh/EdgeForgeStudio/actions/runs/40633901697/job/122636340751)
tested merge-ref `7cc97ed3bdb7b1da0d92bd7536b139f4df989be5` from the original
intent head. Tests and L2 passed; the strict audit exited 1 with seven Authlib
1.7.2 matches and one dnspython 2.8.0 match. The documentation commit had not
changed dependencies. These are eight advisory observations, not eight proven
exploitable Studio paths.

| Original identity | Library issue | Released correction used |
|---|---|---|
| [GHSA-6v38-4h7w-rj9h](https://github.com/authlib/authlib/security/advisories/GHSA-6v38-4h7w-rj9h) | Empty JWS JSON signatures accepted | Authlib 1.9.0 correction included in 1.9.1 |
| [GHSA-fch4-3c6x-j4gc](https://github.com/authlib/authlib/security/advisories/GHSA-fch4-3c6x-j4gc) | Default JWT bearer grant audience validation | Authlib 1.9.0 correction included in 1.9.1 |
| [GHSA-7vr2-2fgp-9w7p](https://github.com/authlib/authlib/security/advisories/GHSA-7vr2-2fgp-9w7p) | Prefixed asymmetric key material used as HMAC key | Authlib 1.9.0 correction included in 1.9.1 |
| [GHSA-c5mf-xmp2-59rc](https://github.com/authlib/authlib/security/advisories/GHSA-c5mf-xmp2-59rc) | ID token disables nonce validation | Authlib 1.9.0 correction included in 1.9.1 |
| [GHSA-x4rv-c3wx-4cr8](https://github.com/authlib/authlib/security/advisories/GHSA-x4rv-c3wx-4cr8) | Unvalidated JAR request_uri fetch | Authlib 1.9.0 correction included in 1.9.1 |
| [GHSA-jj7h-c3hg-m23x](https://github.com/authlib/authlib/security/advisories/GHSA-jj7h-c3hg-m23x) | Userinfo bypass of secure-transport loopback handling | Authlib 1.8.0 correction included in 1.9.1 |
| [GHSA-8m4g-j4wp-wgcg](https://github.com/authlib/authlib/security/advisories/GHSA-8m4g-j4wp-wgcg) | Empty HMAC key accepted | Authlib 1.9.1; source/behavior reconciliation below |
| [GHSA-45c3-73f7-pv4m](https://github.com/rthalley/dnspython/security/advisories/GHSA-45c3-73f7-pv4m) | Excessive DNS compression-pointer work | dnspython 2.9.0 |

Exactly **two** reference pins change: Authlib **1.7.2 -> 1.9.1** and dnspython
**2.8.0 -> 2.9.0**. The other **93** versions remain unchanged, including
FastMCP/fastmcp-slim 3.4.10, MCP 1.30.0, OTel API 1.45.1, certifi 2026.10.19,
Pillow 13.0.0 and the constrained packaging toolchain. Neither corrected library
is added as a direct requirement. FastMCP-slim's existing client/server extras
require Authlib; email-validator requires dnspython. Authlib's newer minimums
(`cryptography>=45.0.1`, `joserfc>=1.6.8`) are already satisfied by 50.0.0/1.7.1.
No supporting transitive change is necessary.

Official [Authlib metadata](https://pypi.org/pypi/authlib/1.9.1/json) requires
Python >=3.10; [dnspython metadata](https://pypi.org/pypi/dnspython/2.9.0/json)
requires >=3.11, consistent with Studio's unchanged floor. Their published
universal wheels were downloaded and SHA-256 checked against PyPI metadata.
All 215 Authlib and 161 dnspython Python source members match the installed bytes
in both clean environments. dnspython's ISC license label changed from the
older descriptive string; no new license flag appeared.

The dnspython DoH/dev/idna extras are not requested by this graph. The existing
SBOM generator can show metadata relationships to installed packages referenced
by optional extras; that does not promise those extras or their newer version
minimums are enabled. Actual constrained installation and `pip check` establish
the requested graph. No optional DoH capability or unrelated upgrade is claimed.

## Authlib advisory wording reconciliation

At this observation, the repository's empty-key advisory still lists affected
`<=1.7.2` and no patched release, while the
[reviewed database entry](https://github.com/advisories/GHSA-8m4g-j4wp-wgcg)
lists affected `<1.9.1` / patched `1.9.1`. Neither wording is silently discarded.
The [tagged 1.9.1 changelog](https://github.com/authlib/authlib/blob/v1.9.1/docs/upgrades/changelog.rst)
explicitly documents empty-key rejection. The released
[`OctKey` source](https://github.com/authlib/authlib/blob/v1.9.1/authlib/jose/rfc7518/oct_key.py)
calls `_check_key` at import and operation-key use, rejecting empty material and
checking unsafe key markers. Matching wheel/installed source hashes and bounded
tests establish the correction in this selected artifact, not an assumption
based solely on version number or scanner silence.

Offline controls imported the checksum-verified old wheels using otherwise
compatible candidate dependencies, not a reconstructed historical environment.
Authlib 1.7.2 accepted empty-key signing/verification for HS256/384/512; 1.9.1
rejects it. New regressions also cover empty byte/string/JWK forms while keeping
valid signing/verification. A 32-pointer synthetic DNS chain was accepted by
2.8.0 and refused by 2.9.0; shallow valid names still parse. These controls do
not probe a live service or prove exposure of Studio's previous deployment.

Other Authlib security changes include stricter OAuth-server audience/JAR/nonce
handling and client registration ownership checks. Studio has no shipped
proxy/OIDC authentication adapter; its identity remains anonymous signed-session
isolation and its Engine/KS transport is local stdio. No application authentication
or transport is added, bypassed or redesigned. This does not clear arbitrary
applications using Authlib's server or OIDC features.

## Executed bounded proof

| Check | Result |
|---|---|
| Clean Python 3.11.15 constrained install, toolchain verifier and pip check | Pass; 95 installed distributions |
| Separate clean Python 3.13.16 macOS environment | Install/verifier/pip check pass; 92 distributions; three existing Python <3.12 backport markers absent |
| Focused security, KA-OFF, Engine/KS adapter, shared-session, manifest 2.0 and regeneration checks | Each Python: **183 passed, 27 skipped** |
| Dependency policy and evidence guard | **4 passed** |
| Offline client compatibility, each Python | Authlib sync/async HTTPX2 clients with mock transport, in-memory FastMCP client round trip and email syntax validation pass |
| Complete candidate strict audit | **95 covered, zero findings, zero skipped/missing packages**, exit 0 |
| Current evidence join | Installed reference, all constraints, strict/generated audit, SBOM and transitive license versions agree exactly |
| Released old/candidate negative controls | Expected old acceptance versus corrected rejection observed; no network/production data |

The 27 skips per focused run are six unavailable real-Engine discovery cases,
17 unavailable Knowledge Server subprocess cases and four Engine-dependent
regeneration parity cases. They are not counted as pass or new sibling proof.
The legacy `authlib.jose` import emits its upstream deprecation warning in the
narrow regression; migration to a new authentication stack is not implied.
The full normal suite and L2 are left to automatic CI, not duplicated locally.

The generator remains unchanged: CycloneDX 7.3.0, pip-licenses 5.5.5 and
pip-audit 2.9.0 run isolated from Studio. The separate complete strict audit
uses the existing `--no-deps --disable-pip --strict` policy. License decisions
`caio` UNKNOWN / `certifi` MPL-2.0 remain; no audit suppression, omitted package,
ignored advisory or failure-policy relaxation was introduced.

## Reproduction, retention and limits

Follow the unchanged constrained setup using Python 3.11, and repeat it in a
separate Python 3.13 environment. Run `scripts/verify-packaging-toolchain.py`,
`python -m pip check`, the two dependency test files and relevant adapter/KA/
session/manifest/regeneration tests. Regenerate current evidence with
`PYTHON=python3.11 bash scripts/generate-dependency-evidence.sh 2026-10-28`;
independently run `pip-audit -r constraints.txt --no-deps --disable-pip
--progress-spinner off --strict --format json`. New advisory queries are dated
observations, not guaranteed byte-identical historical replay.

Raw failed-CI/advisory metadata, wheel/source receipts, clean-install reports,
focused logs, controls and executed task-local helpers remain in private durable
storage outside iCloud, packet identifier `studio-audit-correction-20261028`.
Compact hashes/coverage are committed; full advisory bodies, environments and
raw logs are not. A clean clone can inspect source/evidence and rerun checks;
exact retained observations need authorized access to the private packet.

The initial correction head's required secret scan detected a public source
checksum following a filename containing `key` in this new receipt. The local
redacted report and independent review confirmed that it was not a credential.
The receipt now records separate `member` and `sha256` fields, preserving the
source hashes without an allowlist or scanner-policy change. The failed
observation is retained; the repaired head requires its own CI and re-review.

No image was built or scanned. Earlier image evidence still contains its actual
older Authlib/dnspython copies and retains its Studio/Engine identities; it is
not relabeled to these pins. Pip-private/ensurepip, OS/native/JDK/Maven/stage
findings, font limitations and A11y-01 remain unchanged and OPEN as recorded.
Final selected-pair image proof remains required in release acceptance. No
generated-app runtime campaign, full Suite acceptance, sibling edit, risk
acceptance, publication or merge is performed here.
