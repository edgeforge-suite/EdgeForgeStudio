"""Benign offline native/consumer observations, not exploitability conclusions."""
from __future__ import annotations

import importlib
import json
import os
import platform
import sqlite3
import ssl
import subprocess
import sys
import sysconfig
import tempfile
import zlib
from pathlib import Path

import lxml.etree
import pypdfium2
from cryptography.hazmat.backends.openssl.backend import backend
from PIL import features

from scripts.image_bundle_p_probe import sha256


def capture() -> dict:
    if os.getuid() != 1000 or sys.flags.optimize or platform.machine() != "x86_64":
        raise RuntimeError("Requires the declared non-root AMD64 image")
    native = {}
    roots = [Path(sysconfig.get_path("stdlib")) / "lib-dynload", Path(sysconfig.get_path("purelib"))]
    for root in roots:
        for path in sorted(root.rglob("*.so")):
            command = subprocess.run(["ldd", str(path)], text=True, capture_output=True, timeout=30)
            native[str(path)] = {"sha256": sha256(path), "bytes": path.stat().st_size,
                                 "ldd": command.stdout, "ldd_stderr": command.stderr, "exit_code": command.returncode}
    modules = {}
    for name in ("pyexpat", "_elementtree", "_ssl", "_sqlite3", "zlib", "lxml.etree"):
        module = importlib.import_module(name)
        modules[name] = {"path": module.__file__, "sha256": sha256(Path(module.__file__))}
    with tempfile.TemporaryDirectory(prefix="synthetic-header-proof-") as temporary:
        root = Path(temporary)
        source = root / "synthetic.c"
        source.write_text('#include <stdio.h>\n#include <linux/version.h>\nint main(void){printf("synthetic headers=%d pointer=%zu\\n",LINUX_VERSION_CODE,sizeof(void*));return 0;}\n')
        compiled = subprocess.run(["gcc", str(source), "-o", str(root / "synthetic")], capture_output=True, text=True, timeout=30)
        compiled.check_returncode()
        executed = subprocess.run([str(root / "synthetic")], capture_output=True, text=True, timeout=10, check=True)
    curl = subprocess.run(["curl", "--version"], capture_output=True, text=True, timeout=10, check=True)
    git = subprocess.run(["ldd", "/usr/lib/git-core/git-remote-https"], capture_output=True, text=True, timeout=10, check=True)
    return {"uid": os.getuid(), "python": sys.version, "native_extensions": native, "modules": modules,
            "openssl_runtime": ssl.OPENSSL_VERSION, "sqlite_runtime": sqlite3.sqlite_version,
            "cryptography_private_openssl": backend.openssl_version_text(),
            "lxml_private_libxml": list(lxml.etree.LIBXML_VERSION),
            "lxml_private_libxslt": list(lxml.etree.LIBXSLT_VERSION),
            "pillow_native_features": {name: features.version(name) for name in features.get_supported()},
            "pdfium_runtime": str(pypdfium2.PDFIUM_INFO),
            "zlib_runtime": zlib.ZLIB_RUNTIME_VERSION, "compiler_header_proof": executed.stdout,
            "header_qualification": "Userspace build headers, not the running host kernel or vulnerability clearance",
            "curl_features": curl.stdout, "git_https_linkage": git.stdout,
            "qualification": "No network/exploit traffic; unrecognized static copies and affected caller protocols remain OPEN."}


if __name__ == "__main__":
    print(json.dumps(capture(), sort_keys=True, indent=2))
