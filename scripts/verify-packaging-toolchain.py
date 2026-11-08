#!/usr/bin/env python3
from __future__ import annotations

import re
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

PACKAGING_TOOLS = ("pip", "setuptools", "wheel")


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _expected_versions(path: Path) -> dict[str, str]:
    expected: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line)
        if match and _normalized_name(match.group(1)) in PACKAGING_TOOLS:
            expected[_normalized_name(match.group(1))] = match.group(2)
    missing = set(PACKAGING_TOOLS) - set(expected)
    if missing:
        raise SystemExit(f"missing packaging-tool constraints: {', '.join(sorted(missing))}")
    return expected


def main() -> None:
    constraints = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).resolve().parents[1] / "constraints.txt"
    )
    expected = _expected_versions(constraints)
    actual: dict[str, str] = {}
    for package in PACKAGING_TOOLS:
        try:
            actual[package] = version(package)
        except PackageNotFoundError:
            actual[package] = "not installed"

    mismatches = [
        f"{package}: expected {expected[package]}, found {actual[package]}"
        for package in PACKAGING_TOOLS
        if actual[package] != expected[package]
    ]
    if mismatches:
        raise SystemExit("packaging toolchain mismatch: " + "; ".join(mismatches))

    versions = ", ".join(f"{package}={actual[package]}" for package in PACKAGING_TOOLS)
    print(f"verified packaging toolchain: {versions}")


if __name__ == "__main__":
    main()
