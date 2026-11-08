"""Offline copy-aware runtime evidence; run inside the identified Studio image.

This inventories bytes and benign behavior, not exploitability or risk acceptance.
It neither installs software nor contacts an advisory service.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import importlib.metadata
import inspect
import io
import json
import os
import platform
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_records(root: Path) -> dict:
    records = {}
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_symlink():
            records[path.relative_to(root).as_posix()] = {"symlink": os.readlink(path)}
        elif path.is_file():
            records[path.relative_to(root).as_posix()] = {"sha256": sha256(path), "bytes": path.stat().st_size}
    return records


def wheel_records(path: Path) -> dict:
    with zipfile.ZipFile(path) as wheel:
        selected = {}
        for name in sorted(wheel.namelist()):
            if name.endswith("/"):
                continue
            if (any(part in {"msgpack", "pkg_resources", "setuptools", "urllib3"} for part in name.split("/"))
                    or name.endswith(("/vendor.txt", ".dist-info/METADATA"))):
                data = wheel.read(name)
                selected[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        declarations = {name: wheel.read(name).decode() for name in wheel.namelist() if name.endswith("/vendor.txt")}
    return {"sha256": sha256(path), "members": selected, "vendor_declarations": declarations}


def command(*args: str) -> dict:
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    return {"argv": list(args), "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def tar_directory_regression() -> dict:
    """A synthetic tar member stays wholly beneath a disposable proof root."""
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        destination = root / "destination"
        destination.mkdir()
        data = io.BytesIO()
        with tarfile.open(fileobj=data, mode="w") as archive:
            member = tarfile.TarInfo("../outside/../destination/member.txt")
            member.size = 1
            archive.addfile(member, io.BytesIO(b"x"))
        data.seek(0)
        with tarfile.open(fileobj=data) as archive:
            archive.extractall(destination, filter="data")
        return {"outside_directory_created": (root / "outside").exists(),
                "member_extracted_inside": (destination / "member.txt").read_bytes() == b"x"}


def capture() -> dict:
    if sys.flags.optimize or os.getuid() == 0 or platform.system() != "Linux":
        raise RuntimeError("Probe requires unoptimized Python as the image's normal non-root Linux user")
    stdlib = Path(sys.base_prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}"
    names = {"msgpack", "pkg_resources", "setuptools", "urllib3"}
    search_roots = [Path("/usr/local"), Path("/usr/lib"), Path("/opt"), Path("/workspace")]
    copy_paths = set()
    wheel_paths = set()
    errors = []
    for root in search_roots:
        for directory, children, files in os.walk(root, onerror=lambda error: errors.append(str(error))):
            children[:] = sorted(child for child in children if child not in {"__pycache__", ".git"})
            path = Path(directory)
            if path.name in names:
                copy_paths.add(path)
            wheel_paths.update(path / name for name in files if name.endswith(".whl"))
    if errors:
        raise RuntimeError(f"Incomplete copy inventory: {errors}")
    copies = {path.as_posix(): file_records(path) for path in sorted(copy_paths)}
    wheels = {path.as_posix(): wheel_records(path) for path in sorted(wheel_paths)}
    modules = {}
    # Import setuptools before pkg_resources selects stdlib distutils globally.
    for name in ("setuptools", "base64", "http.cookies", "imaplib", "poplib", "tempfile", "pkgutil", "stringprep",
                 "encodings.idna", "urllib.request", "tarfile", "zipfile", "pyexpat", "pip",
                 "pip._vendor.msgpack", "pip._vendor.pkg_resources", "pip._vendor.urllib3", "urllib3"):
        try:
            module = importlib.import_module(name)
            path = Path(module.__file__)
            modules[name] = {"path": path.as_posix(), "sha256": sha256(path),
                             "version": str(getattr(module, "__version__", ""))}
        except ImportError as error:
            modules[name] = {"import_error": type(error).__name__}
    import pyexpat
    from http.cookies import Morsel
    from tempfile import TemporaryDirectory

    import pip._vendor.msgpack as msgpack
    from pip._vendor.urllib3.connectionpool import HTTPSConnectionPool
    from pip._vendor.urllib3.response import HTTPResponse
    from setuptools.command.egg_info import FileList

    file_list = FileList()
    file_list.files = ["secret_cafe\u0301.txt", "public.txt"]
    file_list.global_exclude("secret_caf\u00e9.txt")

    functions = {}
    for name, function in (("msgpack.Unpacker", msgpack.Unpacker), ("Morsel.js_output", Morsel.js_output),
                           ("TemporaryDirectory._rmtree", TemporaryDirectory._rmtree),
                           ("pip.urllib3.proxy", HTTPSConnectionPool._prepare_proxy),
                           ("pip.urllib3.chunk", HTTPResponse._update_chunk_length)):
        source = inspect.getsource(function).encode()
        functions[name] = {"module": function.__module__, "source_sha256": hashlib.sha256(source).hexdigest()}
    jdk = Path("/opt/java/openjdk")
    return {
        "schema_version": 1, "uid": os.getuid(), "gid": os.getgid(), "python_optimization": sys.flags.optimize,
        "platform": platform.machine(), "pointer_bits": struct.calcsize("P") * 8,
        "copy_search_roots": [path.as_posix() for path in search_roots],
        "copy_search_errors": errors, "sys_path": sys.path,
        "python": sys.version, "python_executable_sha256": sha256(Path(sys.executable)),
        "libpython_sha256": sha256(Path("/usr/local/lib/libpython3.11.so.1.0")),
        "embedded_expat": pyexpat.EXPAT_VERSION, "expat_ldd": command("ldd", pyexpat.__file__),
        "system_expat": command("dpkg-query", "-W", "-f=${Version}", "libexpat1"),
        "modules": modules, "functions": functions, "copies": copies, "bundled_wheels": wheels,
        "distributions": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
                          if d.metadata["Name"].lower() in {"pip", "setuptools", "urllib3", "wheel", "msgpack"}},
        "vendor_declarations": (stdlib / "site-packages/pip/_vendor/vendor.txt").read_text(),
        "jdk_release": (jdk / "release").read_text(), "jdk_files": file_records(jdk),
        "java_version": command("/opt/java/openjdk/bin/java", "-version"),
        "java_modules": command("/opt/java/openjdk/bin/java", "--list-modules"),
        "base64_accepts_outside_url_alphabet": base64.urlsafe_b64decode("+w==").hex(),
        "base64_accepts_trailing_padding_data": base64.b64decode("YQ==Yg==").decode(),
        "msgpack_implementation": msgpack.Unpacker.__module__,
        "tar_directory_regression": tar_directory_regression(),
        "setuptools_normalization_regression": {"remaining_files": file_list.files},
        "pip_check": command(sys.executable, "-m", "pip", "check"),
    }


if __name__ == "__main__":
    print(json.dumps(capture(), indent=2, sort_keys=True))
