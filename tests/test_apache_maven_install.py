"""The Maven image download must fail closed before extraction."""

import hashlib
import io
import tarfile

import pytest

from scripts.install_apache_maven import MAVEN_SHA512, MAVEN_VERSION, install_archive


def _archive(names=("bin/mvn", "LICENSE", "NOTICE"), root_name=None):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name in names:
            member = tarfile.TarInfo(f"{root_name or f'apache-maven-{MAVEN_VERSION}'}/{name}")
            content = b"synthetic test"
            member.size = len(content)
            member.mode = 0o755 if name == "bin/mvn" else 0o644
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


def test_mismatched_checksum_extracts_nothing(tmp_path):
    destination = tmp_path / "maven"
    with pytest.raises(ValueError, match="SHA-512 mismatch"):
        install_archive(_archive(), destination)
    assert not destination.exists()
    assert len(MAVEN_SHA512) == 128


def test_verified_archive_preserves_distribution_and_notices(tmp_path):
    content = _archive()
    destination = tmp_path / "maven"
    install_archive(content, destination, hashlib.sha512(content).hexdigest())
    assert (destination / "bin/mvn").stat().st_mode & 0o111
    assert (destination / "LICENSE").is_file()
    assert (destination / "NOTICE").is_file()


@pytest.mark.parametrize("names, root_name, message", [
    (("bin/mvn", "LICENSE"), None, "missing NOTICE"),
    (("bin/mvn",), "unexpected-root", "Unexpected Apache Maven archive root"),
])
def test_incomplete_or_unexpected_archive_is_rejected(tmp_path, names, root_name, message):
    content = _archive(names, root_name)
    destination = tmp_path / "maven"
    with pytest.raises(ValueError, match=message):
        install_archive(content, destination, hashlib.sha512(content).hexdigest())
    assert not destination.exists()
