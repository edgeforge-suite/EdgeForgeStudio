"""Verify an exported OCI image's index, platform, config and layer bytes.

Scanner serializers and filesystem DiffIDs are deliberately recorded separately
from the registry-format manifest and compressed layer identities.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import tarfile
from pathlib import Path


def verify(path: Path, expected_index: str) -> dict:
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", expected_index):
        raise ValueError("Invalid expected image index")
    with tarfile.open(path) as archive:
        def blob(descriptor):
            digest = descriptor["digest"]
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("Invalid OCI blob identity")
            stream = archive.extractfile("blobs/sha256/" + digest[7:])
            if stream is None:
                raise ValueError("Missing OCI blob")
            data = stream.read()
            if len(data) != descriptor["size"] or "sha256:" + hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("OCI blob hash/size mismatch")
            return data

        root = json.load(archive.extractfile("index.json"))
        indices = [item for item in root["manifests"] if item["digest"] == expected_index]
        if len(indices) != 1:
            raise ValueError("Export does not contain exactly the expected image index")
        index = json.loads(blob(indices[0]))
        platforms = [item for item in index["manifests"]
                     if item.get("platform", {}).get("os") == "linux"
                     and item["platform"].get("architecture") == "amd64"]
        if len(platforms) != 1:
            raise ValueError("Image must have one declared assessed linux/amd64 descriptor")
        platform = platforms[0]
        manifest = json.loads(blob(platform))
        config = json.loads(blob(manifest["config"]))
        if config.get("os") != "linux" or config.get("architecture") != "amd64":
            raise ValueError("Config and declared assessed platform disagree")
        diff_ids = config["rootfs"]["diff_ids"]
        if len(diff_ids) != len(manifest["layers"]):
            raise ValueError("Layer/DiffID count mismatch")
        layers = []
        for descriptor, diff_id in zip(manifest["layers"], diff_ids, strict=True):
            data = blob(descriptor)
            if descriptor["mediaType"].endswith("+gzip"):
                raw = gzip.decompress(data)
            elif descriptor["mediaType"] == "application/vnd.oci.image.layer.v1.tar":
                raw = data
            else:
                raise ValueError("Unsupported OCI layer encoding")
            if "sha256:" + hashlib.sha256(raw).hexdigest() != diff_id:
                raise ValueError("Filesystem DiffID mismatch")
            layers.append({"compressed_digest": descriptor["digest"], "compressed_bytes": len(data),
                           "filesystem_diff_id": diff_id})
        return {"verified": True, "index_digest": expected_index, "platform": "linux/amd64",
                "platform_manifest_digest": platform["digest"], "config_digest": manifest["config"]["digest"],
                "layers": layers, "config_user": config["config"].get("User", ""), "created": config["created"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--index", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive, args.index), indent=2))


if __name__ == "__main__":
    main()
