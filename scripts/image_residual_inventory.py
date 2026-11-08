"""Read retained filesystem tar bytes without extracting or executing content."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


def archive_components(data: bytes, name: str, depth: int = 0) -> list[dict]:
    if depth > 3:
        raise ValueError("Nested archive inspection depth exceeded")
    rows = []
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Duplicate archive member")
        for member in sorted(archive.namelist()):
            info = archive.getinfo(member)
            if info.file_size > 256 * 1024 * 1024:
                raise ValueError("Archive member exceeds bounded inspection size")
            if not info.is_dir():
                with archive.open(member) as stream:
                    header = stream.read(64)
                if header.startswith((b"\x7fELF", b"MZ")):
                    content = archive.read(member)
                    rows.append({"archive": name, "member": member, "bytes": len(content),
                                 "sha256": hashlib.sha256(content).hexdigest(),
                                 "native_format": "ELF" if header.startswith(b"\x7fELF") else "PE/MS-DOS",
                                 "version_applicability": "Not inferred from archive presence; reconcile owning component/advisory."})
            if member.endswith("/pom.properties") and member.startswith("META-INF/maven/"):
                content = archive.read(member)
                properties = dict(line.split("=", 1) for line in content.decode().splitlines()
                                  if "=" in line and not line.startswith("#"))
                if not {"groupId", "artifactId", "version"} <= properties.keys():
                    raise ValueError("Incomplete Maven component identity")
                rows.append({"archive": name, "member": member, "sha256": hashlib.sha256(content).hexdigest(),
                             **{key: properties[key] for key in ("groupId", "artifactId", "version")}})
            elif member.endswith((".jar", ".whl", ".zip")):
                content = archive.read(member)
                rows.extend(archive_components(content, name + "!" + member, depth + 1))
    return rows


def inventory(path: Path) -> dict:
    files, links, native, archives = {}, {}, {}, {}
    with tarfile.open(path) as archive:
        names = set()
        for member in archive:
            name = member.name.removeprefix("./").lstrip("/")
            if ".." in PurePosixPath(name).parts or name in names:
                raise ValueError("Ambiguous filesystem member")
            names.add(name)
            if member.issym():
                links["/" + name] = member.linkname
                continue
            if not (member.isfile() or member.islnk()):
                continue
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError("Missing filesystem bytes")
            header = stream.read(64)
            size = len(header)
            digest = hashlib.sha256(header)
            while block := stream.read(1024 * 1024):
                digest.update(block)
                size += len(block)
            record = {"sha256": digest.hexdigest(), "bytes": size,
                      "mode": member.mode, "uid": member.uid, "gid": member.gid}
            files["/" + name] = record
            if header.startswith(b"\x7fELF"):
                if len(header) < 20 or header[4] not in (1, 2) or header[5] not in (1, 2):
                    raise ValueError("Malformed native ELF identity")
                byteorder = "little" if header[5] == 1 else "big"
                native["/" + name] = {**record, "format": "ELF", "bits": 32 if header[4] == 1 else 64,
                                      "machine": int.from_bytes(header[18:20], byteorder)}
            elif header.startswith(b"MZ"):
                native["/" + name] = {**record, "format": "PE/MS-DOS; target applicability unresolved"}
            if name.endswith((".jar", ".whl", ".zip")):
                stream = archive.extractfile(member)
                data = stream.read()
                archives["/" + name] = {**record, "components": archive_components(data, "/" + name)}
    if not files or "/var/lib/dpkg/status" not in files:
        raise ValueError("Incomplete Linux package filesystem export")
    return {"files": files, "symlinks": links, "native": native, "archives": archives,
            "qualification": "Every regular/hard-linked file is hashed. ELF/PE and bounded nested ZIP/JAR identities are enumerated, not blanket advisory coverage. Unknown embedded/static identities require owner investigation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--filesystem", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(inventory(args.filesystem), sort_keys=True, indent=2) + "\n")


if __name__ == "__main__":
    main()
