# Studio PyJWT audit follow-up - 2026-09-30

This is the bounded dependency-audit repair for candidate
`EF-V5-M2-STUDIO-PYJWT-DISCLOSURES-S1` revision 1. It is **not** a fresh
whole-image advisory assessment, M2 clearance, risk acceptance, or a release
pairing. The [historical Maven image assessment](studio-maven-image-remediation.md)
and its open findings remain separate.

## Input and failure

| Input | Identity |
|---|---|
| Studio base | `59ba24b0a8212d195864a78f80d5cd47eabfc841` |
| Tested Studio source/recipe commit | `f22f941d0981135e4f3fa24313266449418e59db` |
| Frozen, read-only Engine build/stdio input | `584e4bf635ac12821496a52d20c3a03a6e73a92c` |
| `requirements.txt` SHA-256 | `d2c9b40eff8805e62be925149a87f7f4d2b35f15941c80aa3542521b3a34d3e1` |
| `constraints.txt` SHA-256 | `a5d788695ef6d67a6013607d6c6ff892ced6dfc5d7743c92140a27195d99667e` |
| Dockerfile SHA-256 | `2e2824c878e79be554a169c131b8303ac570fabfe371ebf2a61e18a2448542ec` |

The [required post-merge job](https://github.com/santosh-sh/EdgeForgeStudio/actions/runs/36735699422/job/109956682329)
failed on 2026-09-30 with 11 PyJWT `2.13.0` advisory matches, each listing
`2.14.0` as a fix. That is an advisory finding in a transitive package, not
evidence of 11 exploitable Studio call paths. Installed package metadata shows
the path `fastmcp==3.4.0` -> `fastmcp-slim[client,server]==3.4.0` ->
`mcp==1.28.1` -> `pyjwt[crypto]>=2.10.1`. The selected `2.15.0` release
supports Python 3.11 according to [PyPI](https://pypi.org/project/PyJWT/2.15.0/);
its [tagged changelog](https://github.com/jpadilla/pyjwt/blob/2.15.0/CHANGELOG.rst)
records additional security/error-handling and JWK-cache changes beyond 2.14.
Studio's anonymous shared-mode identity has **not** become JWT authentication.

## Dependency and test result

The clean Python 3.11 installation used the repository's constrained packaging
procedure. `pip==26.2.1`, `setuptools==83.0.0`, and `wheel==0.48.0` passed
`scripts/verify-packaging-toolchain.py`; `pip check` found no broken
requirements. All 95 fully pinned constraints were installed at their exact
versions, without missing, duplicate, extra, or unpinned packages. Relative
to the prior 2026-09-19 committed constraints, **PyJWT 2.13.0 -> 2.15.0 is the
only name/version delta**. `jwt`, `fastmcp`, `mcp`, and `app.main` import.

The established `pip-audit==2.9.0` command below returned exit 0 and "No
known vulnerabilities found" on the complete constraints. Neither this
strict result nor the refreshed committed snapshot substitutes for a future
live audit. The delivered evidence generator, with isolated
`cyclonedx-bom==7.3.0` and `pip-licenses==5.5.5`, produced matching CycloneDX
1.6 and direct-audit inventories of 95 packages; both record PyJWT `2.15.0`,
and the audit JSON has zero advisory matches. The generator's exit status
alone was **not** treated as the blocking audit result. It and pip-audit query
public package-name/version metadata at
`https://pypi.org/pypi/<name>/<version>/json`; no private source, project
content, secrets, or image was uploaded. Declared-license status is unchanged;
`caio` (UNKNOWN) and `certifi` (MPL-2.0) remain flagged for adopter review.

```text
pip-audit -r constraints.txt --no-deps --disable-pip --progress-spinner off --strict
pytest tests -q -m 'not smoke'                         2205 passed, 17 skipped, 29 deselected
pytest tests/test_dependency_audit_policy.py tests/test_appbuilder_integration.py tests/test_studio_settings.py -q
                                                        72 passed
pytest tests/smoke/test_l2_two_session_smoke.py -q -m 'smoke and l2'
                                                        1 passed
```

With the frozen Engine checkout, the real local stdio
`list_target_profiles` tool returned six profiles, including
`springboot-legacy-compatible`. This was an actual Engine process call, not a
mock or a new Studio MCP surface.

## Fresh image installation and launch

One new, task-owned image was built from the tested Studio commit, unchanged
Dockerfile and frozen Engine archive. Build target and run target were
`linux/amd64`; build args were `APP_UID=1000` and `APP_GID=1000`.

| Material or result | Identity |
|---|---|
| `python:3.11-slim-bookworm` material | `sha256:a36c24f9cbdf4fd0f52d67f0823eeac19c2028c637cecc392d97f980d4fec56b` |
| `eclipse-temurin:21-jdk` material | `sha256:4d06038800655fe1211760cd561de70ef2ed7a47f5d69255e9834414602b7026` |
| Local image (`linux/amd64`) | `sha256:ff97fb0ee901e2e759d2143fee83538ac1ffeb17248c745a8f3287e9ca264c89` |

The image's default user is `appuser`; an offline run reported UID `1000`,
PyJWT `2.15.0`, FastMCP `3.4.0`, and MCP `1.28.1`, and imported `app.main`.
An offline image `pip check` found no broken requirements. The existing Docker
launch smoke was run with `EDGEFORGE_STUDIO_IMAGE_PREBUILT` set to **this newly
built image**, not the historical #305 image: **1 passed**. It proved an
unmounted app import and loopback HTTP 200 from a non-root container. The
retained local BuildKit receipt identifies the source commit, Engine context,
base materials and image digest; the transient tag and full local build logs
are not committed. Floating base tags and live APT/PyPI resolution mean the
receipt identifies **this build**, not a promise that rebuilding later yields
identical bytes.

The old #305 image identity belongs to different Studio/Engine inputs and is
not reused as proof here. The [independent #305 font observation](https://github.com/santosh-sh/EdgeForgeStudio/pull/305#issuecomment-5883816589)
is a disclosed limitation: the lean image lacks Java font-rendering support by
default, so adopter text-rendering paths may need an extended, reassessed
image. No new font experiment, broad image scan, Maven matrix, Suite L5,
release-pair rebuild, or image publication was performed for this Python pin.
