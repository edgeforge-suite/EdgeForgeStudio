"""Install the reviewed Apache Maven distribution in a disposable image stage."""

from __future__ import annotations

import argparse
import hashlib
import io
import tarfile
import tempfile
import urllib.request
from pathlib import Path

MAVEN_VERSION = "3.9.16"
# Apache's official release checksum; do not replace with a freshly downloaded value.
MAVEN_SHA512 = (
    "831a8591fe20c8243b1dbe7d71e3244f31d1665b0804b2e825e38cbbe5ce0cafb"
    "8338851f90780735568773e0a6cd07bbec107cda0b896b008b861075358b6f6"
)
MAVEN_URL = (
    "https://archive.apache.org/dist/maven/maven-3/"
    f"{MAVEN_VERSION}/binaries/apache-maven-{MAVEN_VERSION}-bin.tar.gz"
)


def install_archive(content: bytes, destination: Path, expected_sha512: str = MAVEN_SHA512) -> None:
    if hashlib.sha512(content).hexdigest() != expected_sha512:
        raise ValueError("Apache Maven archive SHA-512 mismatch; nothing extracted")
    root_name = f"apache-maven-{MAVEN_VERSION}"
    with tempfile.TemporaryDirectory() as temporary:
        with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
            if any(member.name.split("/", 1)[0] != root_name for member in archive.getmembers()):
                raise ValueError("Unexpected Apache Maven archive root")
            archive.extractall(temporary, filter="data")
        root = Path(temporary) / root_name
        for required in ("bin/mvn", "LICENSE", "NOTICE"):
            if not (root / required).is_file():
                raise ValueError(f"Apache Maven archive missing {required}")
        root.rename(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Use a local archive with the same reviewed pin")
    parser.add_argument("--destination", type=Path, default=Path("/opt/maven"))
    args = parser.parse_args()
    if args.archive:
        content = args.archive.read_bytes()
    else:
        with urllib.request.urlopen(MAVEN_URL, timeout=120) as response:
            content = response.read()
    install_archive(content, args.destination)


if __name__ == "__main__":
    main()
