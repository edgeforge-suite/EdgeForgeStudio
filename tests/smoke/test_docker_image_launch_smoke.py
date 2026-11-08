"""The built image must launch on its own, without Compose's source mount.

docker-compose.yml bind-mounts this repo over /workspace/EdgeForgeStudio for
the dev inner loop, which can hide a missing `app/` COPY in the Dockerfile --
the image works under Compose even if it could never launch by itself. A
source-string check on the CMD instruction cannot catch this class of defect
(PR #279 review): it has to actually build and run the plain image.

EDGEFORGE_STUDIO_IMAGE_PREBUILT skips this test's build and proves only the named
image. Bind a pass to the current Dockerfile only with an identified fresh build
receipt for that image.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.smoke

ROOT = Path(__file__).resolve().parent.parent.parent


def _require_docker_image_dependencies() -> Path:
    if shutil.which("docker") is None:
        pytest.skip("Docker image launch smoke requires the docker CLI")
    engine_repo = Path(os.environ.get("EDGEFORGE_STUDIO_IMAGE_ENGINE_CONTEXT", ROOT.parent / "EdgeForge"))
    if not (engine_repo / "appbuilder").is_dir():
        pytest.skip(
            "Docker image launch smoke requires a sibling EdgeForge checkout "
            "(Dockerfile's additional_contexts build input)"
        )
    return engine_repo


def test_built_image_imports_app_main_without_a_bind_mount() -> None:
    prebuilt = os.environ.get("EDGEFORGE_STUDIO_IMAGE_PREBUILT")
    image_tag = prebuilt or f"edgeforge-studio-image-launch-smoke:{uuid.uuid4().hex}"
    if not prebuilt:
        engine_repo = _require_docker_image_dependencies()
        build = subprocess.run(
            [
                "docker", "build",
                "--platform", "linux/amd64",
                "--build-context", f"edgeforge_engine={engine_repo}",
                "-t", image_tag,
                str(ROOT),
            ],
            capture_output=True, text=True, timeout=600,
        )
        assert build.returncode == 0, f"image build failed:\n{build.stdout}\n{build.stderr}"

    try:
        # Prove both the import and the actual default server command work.
        run = subprocess.run(
            ["docker", "run", "--rm", "--platform", "linux/amd64", image_tag,
             "python", "-c", "import app.main, os; print(os.getuid())"],
            capture_output=True, text=True, timeout=60,
        )
        assert run.returncode == 0, (
            "the built image cannot import app.main on its own, with no "
            f"Compose bind mount providing it:\n{run.stdout}\n{run.stderr}"
        )
        assert run.stdout.strip() == "1000", "image import did not run as the non-root app user"

        server = subprocess.run(
            ["docker", "run", "--detach", "--platform", "linux/amd64",
             "--publish", "127.0.0.1::8083", image_tag],
            capture_output=True, text=True, timeout=60,
        )
        assert server.returncode == 0, f"image server failed to launch: {server.stderr}"
        container_id = server.stdout.strip()
        try:
            inspect = subprocess.run(
                ["docker", "inspect", "--format", "{{.Config.User}} {{json .Mounts}}", container_id],
                capture_output=True, text=True, timeout=30, check=True,
            )
            assert inspect.stdout.strip() == "appuser []", "server must be non-root and mount-free"
            port = subprocess.run(
                ["docker", "port", container_id, "8083/tcp"],
                capture_output=True, text=True, timeout=30, check=True,
            ).stdout.strip().rsplit(":", 1)[1]
            deadline = time.monotonic() + 45
            while True:
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2) as response:
                        assert response.status == 200
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        logs = subprocess.run(
                            ["docker", "logs", container_id], capture_output=True, text=True,
                        )
                        pytest.fail(f"image server did not become ready: {logs.stdout}\n{logs.stderr}")
                    time.sleep(0.5)
        finally:
            subprocess.run(["docker", "rm", "--force", container_id], capture_output=True)
    finally:
        if not prebuilt:
            subprocess.run(["docker", "rmi", "-f", image_tag], capture_output=True)
