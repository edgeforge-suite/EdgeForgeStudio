import gzip
import hashlib
import io
import json
import tarfile

import pytest

from scripts.verify_image_oci import verify


def fixture_archive(tmp_path, mutation):
    blobs = {}

    def store(data, kind):
        digest = "sha256:" + hashlib.sha256(data).hexdigest()
        blobs["blobs/sha256/" + digest[7:]] = data
        return {"digest": digest, "size": len(data), "mediaType": kind}

    raw = b"synthetic filesystem layer"
    layer = store(gzip.compress(raw), "application/vnd.oci.image.layer.v1.tar+gzip")
    config = {"os": "linux", "architecture": "arm64" if mutation == "platform" else "amd64",
              "created": "2026-10-11T00:00:00Z", "config": {"User": "appuser"},
              "rootfs": {"diff_ids": ["sha256:" + hashlib.sha256(b"wrong" if mutation == "diffid" else raw).hexdigest()]}}
    if mutation == "default-root-stage":
        config["config"] = {}
    config_desc = store(json.dumps(config).encode(), "application/vnd.oci.image.config.v1+json")
    manifest = store(json.dumps({"config": config_desc, "layers": [layer]}).encode(), "application/vnd.oci.image.manifest.v1+json")
    manifest["platform"] = {"os": "linux", "architecture": "amd64"}
    index = store(json.dumps({"manifests": [manifest]}).encode(), "application/vnd.oci.image.index.v1+json")
    blobs["index.json"] = json.dumps({"manifests": [index]}).encode()
    if mutation == "changed":
        blobs["blobs/sha256/" + layer["digest"][7:]] = b"changed"
    if mutation == "missing":
        blobs.pop("blobs/sha256/" + config_desc["digest"][7:])
    path = tmp_path / "image.tar"
    with tarfile.open(path, "w") as archive:
        for name, data in blobs.items():
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return path, index["digest"]


@pytest.mark.parametrize("mutation", [None, "changed", "missing", "platform", "diffid", "wrong-image"])
def test_image_chain_rejects_mismatched_artifacts(tmp_path, mutation):
    path, index = fixture_archive(tmp_path, mutation)
    if mutation == "wrong-image":
        index = "sha256:" + "f" * 64
    if mutation:
        with pytest.raises((ValueError, KeyError)):
            verify(path, index)
    else:
        result = verify(path, index)
        assert result["verified"] is True
        assert result["platform_manifest_digest"] != result["config_digest"] != result["index_digest"]
        assert result["layers"][0]["compressed_digest"] != result["layers"][0]["filesystem_diff_id"]


def test_stage_without_user_reports_docker_default_without_claiming_non_root(tmp_path):
    path, index = fixture_archive(tmp_path, "default-root-stage")
    result = verify(path, index)
    assert result["config_user"] == ""
