from __future__ import annotations

import ast
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import StreamingResponse

from app.main import app

ROOT = Path(__file__).resolve().parents[1]


def test_all_template_responses_use_request_first_signature() -> None:
    calls: list[tuple[Path, ast.Call]] = []
    for path in sorted((ROOT / "app/routes").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr == "TemplateResponse":
                calls.append((path, node))

    assert calls, "route inventory found no TemplateResponse calls"
    for path, call in calls:
        assert call.args, f"{path}:{call.lineno} has no request argument"
        first = call.args[0]
        assert isinstance(first, ast.Name) and first.id == "request", (
            f"{path}:{call.lineno} must use TemplateResponse(request, name, context)"
        )


def test_real_app_static_files_work_with_starlette_1x() -> None:
    response = TestClient(app).get("/static/css/studio.css")

    assert response.status_code == 200
    assert "--brand-navy" in response.text


def test_streaming_response_works_with_starlette_1x_test_client() -> None:
    compatibility_app = FastAPI()

    @compatibility_app.get("/stream")
    def stream() -> StreamingResponse:
        return StreamingResponse(iter((b"studio-", b"stream")))

    response = TestClient(compatibility_app).get("/stream")

    assert response.status_code == 200
    assert response.content == b"studio-stream"
