# Dependency License Inventory — EdgeForge Studio (declared deps)

> **Import-gate G4 evidence.** Resolved license inventory of Studio's declared
> dependencies plus a resolved transitive scan. See [`dependencies.md`](dependencies.md)
> for scope and tooling.
>
> **Generated:** 2026-11-13, with **pip-licenses 5.5.5**.

## Notable licenses — summary

**All declared dependencies are permissive (MIT / BSD / Apache-2.0). No copyleft (GPL / LGPL / AGPL / MPL / EPL) and no UNKNOWN-license packages are present among the declared surface.**

## Declared dependencies

Machine-readable copy: [`dependency-licenses.csv`](dependency-licenses.csv).

| Package | Declared | Resolved | License | Scope |
|---|---|---|---|---|
| `fastapi` | `fastapi==0.138.1` | 0.138.1 | MIT | runtime |
| `fastmcp` | `fastmcp==3.4.10` | 3.4.10 | Apache-2.0 | runtime |
| `httpx` | `httpx==0.28.1` | 0.28.1 | BSD License | runtime |
| `httpx2` | `httpx2==2.12.0` | 2.12.0 | BSD-3-Clause | test |
| `Jinja2` | `jinja2==3.1.6` | 3.1.6 | BSD License | runtime |
| `jsonschema` | `jsonschema>=4.23,<5` | 4.26.0 | MIT | runtime |
| `openpyxl` | `openpyxl>=3.1.0` | 3.1.5 | MIT License | runtime |
| `pdfplumber` | `pdfplumber>=0.11.0` | 0.11.10 | MIT License | runtime |
| `pydantic` | `pydantic==2.11.7` | 2.11.7 | MIT | runtime |
| `pytest` | `pytest==9.0.3` | 9.0.3 | MIT | test |
| `pytest-asyncio` | `pytest-asyncio==1.4.0` | 1.4.0 | Apache-2.0 | test |
| `python-docx` | `python-docx>=1.1.0` | 1.2.0 | MIT License | runtime |
| `python-multipart` | `python-multipart==0.0.31` | 0.0.31 | Apache-2.0 | runtime |
| `PyYAML` | `pyyaml==6.0.2` | 6.0.2 | MIT License | runtime |
| `ruamel.yaml` | `ruamel.yaml==0.19.1` | 0.19.1 | MIT License | runtime |
| `starlette` | `starlette==1.3.1` | 1.3.1 | BSD-3-Clause | runtime |
| `uvicorn` | `uvicorn[standard]>=0.35,<1` | 0.49.0 | BSD-3-Clause | runtime |

## Transitive scan

Machine-readable copy: [`dependency-licenses-transitive.csv`](dependency-licenses-transitive.csv).

**Flagged transitive licenses present:** `caio` (UNKNOWN), `certifi` (Mozilla Public License 2.0 (MPL 2.0)). Review before import.

The transitive inventory covers the resolved project environment used for
[`sbom.cdx.json`](sbom.cdx.json). It is an automated scan, not a substitute for
the adopting organization's legal/license review.
