"""Offline Bundle P venv/toolchain proof inside the actual non-root image.

Supply four official wheels plus a verified filename-to-SHA256 manifest. This
helper never downloads packages; run with container networking disabled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TOOLS = {"pip": "26.2.1", "setuptools": "83.0.0", "wheel": "0.48.0", "packaging": "26.2"}


def constrained_tools(path: Path) -> dict[str, str]:
    selected = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)==([^\s;]+)", line.split("#", 1)[0].strip())
        if match and match[1] in TOOLS:
            if match[1] in selected:
                raise ValueError(f"Duplicate toolchain constraint: {match[1]}")
            selected[match[1]] = match[2]
    if set(selected) != set(TOOLS):
        raise ValueError("Constraints must exactly pin all four toolchain packages")
    return selected


def verify_wheelhouse(root: Path, hashes: dict[str, str], tools: dict[str, str] | None = None) -> list[Path]:
    selected = TOOLS if tools is None else tools
    if set(selected) != set(TOOLS):
        raise ValueError("Expected four toolchain packages")
    names = {f"{name}-{version}-py3-none-any.whl" for name, version in selected.items()}
    if set(hashes) != names or {path.name for path in root.iterdir()} != names:
        raise ValueError("Wheelhouse must contain exactly the four approved toolchain wheels")
    paths = []
    for name in sorted(names):
        path = root / name
        expected = hashes[name]
        if path.is_symlink() or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ValueError("Invalid wheel hash or symlink")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Wheel SHA256 mismatch: {name}")
        paths.append(path)
    return paths


def execute(wheelhouse: Path, hashes: dict[str, str], tools: dict[str, str] | None = None) -> dict:
    if sys.flags.optimize or os.getuid() == 0 or sys.version_info[:3] != (3, 13, 16):
        raise RuntimeError("Requires unoptimized Python 3.13.16 as the image's non-root user")
    selected = TOOLS if tools is None else tools
    paths = verify_wheelhouse(wheelhouse, hashes, selected)
    env = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
    commands = []

    def run(argv, **kwargs):
        completed = subprocess.run(argv, env=env, text=True, capture_output=True, timeout=120, **kwargs)
        commands.append({"argv": [str(arg) for arg in argv], "exit_code": completed.returncode,
                         "stdout": completed.stdout, "stderr": completed.stderr})
        completed.check_returncode()
        return completed.stdout

    with tempfile.TemporaryDirectory(prefix="bundle-p-bootstrap-") as temporary:
        root = Path(temporary)
        venv = root / "venv"
        run([sys.executable, "-m", "venv", "--without-pip", str(venv)])
        python = str(venv / "bin/python")
        run([python, "-m", "ensurepip", "--upgrade"])
        seed = json.loads(run([python, "-c", "import importlib.metadata as m,json; print(json.dumps({d.metadata['Name']:d.version for d in m.distributions()}))"]))
        if seed != {"pip": TOOLS["pip"]}:
            raise RuntimeError(f"Unexpected upstream venv seed: {seed}")
        run([python, "-m", "pip", "install", "--no-index", "--no-deps", *map(str, paths)])
        versions = json.loads(run([python, "-c", "import importlib.metadata as m,json; print(json.dumps({n:m.version(n) for n in ('pip','setuptools','wheel','packaging')}))"]))
        if versions != selected:
            raise RuntimeError(f"Explicit toolchain versions differ: {versions}")
        run([python, "-m", "pip", "check"])
        package = root / "synthetic-package"
        package.mkdir()
        (package / "setup.py").write_text("from setuptools import setup\nsetup(name='synthetic-bootstrap-proof', version='0.0.0', py_modules=['synthetic_module'])\n")
        (package / "synthetic_module.py").write_text("VALUE = 'synthetic offline build'\n")
        output = root / "built"
        run([python, "-m", "pip", "wheel", "--no-index", "--no-deps", "--no-build-isolation", "--wheel-dir", str(output), str(package)])
        built = list(output.glob("*.whl"))
        if len(built) != 1:
            raise RuntimeError("Offline wheel build did not produce one artifact")
        result = {"result": "pass", "uid": os.getuid(), "python": sys.version,
                  "seed": seed, "explicit_toolchain": versions, "wheelhouse_sha256": hashes,
                  "built_wheel_sha256": hashlib.sha256(built[0].read_bytes()).hexdigest(),
                  "commands": commands}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--hashes", type=Path, required=True)
    parser.add_argument("--constraints", type=Path, help="Current explicit toolchain; omission retains the historical Bundle P pins")
    args = parser.parse_args()
    tools = constrained_tools(args.constraints) if args.constraints else None
    print(json.dumps(execute(args.wheelhouse, json.loads(args.hashes.read_bytes()), tools), indent=2))


if __name__ == "__main__":
    main()
