from __future__ import annotations

import json
from pathlib import Path


def write_openapi_cache(
    directory: Path,
    url: str,
    content: str = "openapi: 3.1.0\n",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "openapi.yaml"
    source.write_text(content, encoding="utf-8")
    cache = directory / "openapi-cache.json"
    cache.write_text(
        json.dumps({"version": 1, "sources": {url: source.name}}),
        encoding="utf-8",
    )
    return cache
