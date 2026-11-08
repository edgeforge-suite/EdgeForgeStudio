"""Extract deterministic review copies from canonical sample-pack projects."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


class SamplePackDerivativeError(ValueError):
    """Raised when a canonical project cannot produce its fixed derivatives."""


DERIVATIVE_MAP: dict[str, dict[str, tuple[str | int, ...]]] = {
    "fs-account-servicing": {
        "contracts/account-api-spec.json": ("upstream_interfaces", 0, "spec_content"),
        "contracts/account-staging-table.sql": ("data_handoffs", 0, "ddl_content"),
        "samples/sample-createaccount-request.json": (
            "upstream_interfaces",
            0,
            "operations",
            0,
            "request_sample_content",
        ),
        "samples/sample-createaccount-response.json": (
            "upstream_interfaces",
            0,
            "operations",
            0,
            "response_sample_content",
        ),
    },
    "hc-authorization-status": {
        "contracts/authorization-api-spec.json": (
            "upstream_interfaces",
            0,
            "spec_content",
        ),
        "contracts/authorization-schema.xsd": (
            "downstream_interfaces",
            0,
            "xsd_content",
        ),
        "contracts/authorization-staging-table.sql": (
            "data_handoffs",
            0,
            "ddl_content",
        ),
        "samples/sample-createauthorization-request.json": (
            "upstream_interfaces",
            0,
            "operations",
            0,
            "request_sample_content",
        ),
        "samples/sample-createauthorization-response.json": (
            "upstream_interfaces",
            0,
            "operations",
            0,
            "response_sample_content",
        ),
    },
    "ins-claims-intake-router": {
        "contracts/claim-intake-api-spec.json": (
            "upstream_interfaces",
            0,
            "spec_content",
        ),
        "contracts/auto-claims-api-spec.json": (
            "downstream_interfaces",
            0,
            "spec_content",
        ),
        "contracts/property-claims-api-spec.json": (
            "downstream_interfaces",
            1,
            "spec_content",
        ),
        "contracts/specialty-claims-api-spec.json": (
            "downstream_interfaces",
            2,
            "spec_content",
        ),
    },
}


def _canonical_project_path(pack_dir: Path) -> Path:
    pack_id = pack_dir.name
    return pack_dir / "project" / f"{pack_id}.edgeforge-project.json"


def _read_source(value: Any, source_path: Sequence[str | int], *, pack_id: str) -> str:
    current = value
    traversed: list[str] = []
    for part in source_path:
        traversed.append(f"[{part}]" if isinstance(part, int) else part)
        location = ".".join(traversed).replace(".[", "[")
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                raise SamplePackDerivativeError(
                    f"{pack_id}: derivative source '{location}' is absent or is not a list item"
                )
            current = current[part]
        else:
            if not isinstance(current, Mapping) or part not in current:
                raise SamplePackDerivativeError(
                    f"{pack_id}: derivative source '{location}' is absent or is not an object field"
                )
            current = current[part]

    if not isinstance(current, str):
        location = ".".join(str(part) for part in source_path)
        raise SamplePackDerivativeError(
            f"{pack_id}: derivative source '{location}' must be a string, got "
            f"{type(current).__name__}"
        )
    return current


def extract_pack_derivatives(pack_dir: Path) -> dict[str, bytes]:
    """Return the fixed review derivatives for one canonical pack."""
    pack_id = pack_dir.name
    derivative_map = DERIVATIVE_MAP.get(pack_id)
    if derivative_map is None:
        raise SamplePackDerivativeError(f"Unknown sample pack '{pack_id}'")

    project_path = _canonical_project_path(pack_dir)
    try:
        project = json.loads(project_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SamplePackDerivativeError(
            f"{pack_id}: canonical project is missing at '{project_path}'"
        ) from exc
    except json.JSONDecodeError as exc:
        raise SamplePackDerivativeError(
            f"{pack_id}: canonical project is not valid JSON: {exc}"
        ) from exc

    return {
        relative_path: _read_source(project, source_path, pack_id=pack_id).encode("utf-8")
        for relative_path, source_path in derivative_map.items()
    }


def compare_pack_derivatives(pack_dir: Path) -> list[str]:
    """Return deterministic mismatch diagnostics for committed review copies."""
    mismatches: list[str] = []
    for relative_path, expected in extract_pack_derivatives(pack_dir).items():
        derivative_path = pack_dir / relative_path
        if not derivative_path.exists():
            mismatches.append(f"{relative_path}: committed review copy is missing")
            continue
        if derivative_path.read_bytes() != expected:
            mismatches.append(f"{relative_path}: differs from the canonical project JSON")
    return mismatches


def write_pack_derivatives(pack_dir: Path) -> None:
    """Regenerate one pack's fixed review copies byte-for-byte."""
    for relative_path, content in extract_pack_derivatives(pack_dir).items():
        target = pack_dir / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "docs" / "sample-packs",
        help="sample-pack root (default: docs/sample-packs)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare committed derivatives instead of regenerating them",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    failures: list[str] = []
    for pack_id in DERIVATIVE_MAP:
        pack_dir = args.root / pack_id
        if args.check:
            failures.extend(
                f"{pack_id}/{message}" for message in compare_pack_derivatives(pack_dir)
            )
        else:
            write_pack_derivatives(pack_dir)

    if failures:
        for failure in failures:
            print(failure)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
