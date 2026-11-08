"""Local Build & Run helpers for Step 8."""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path

from app.models.project import BuildRunRoute, BuildRunState, ProjectSession
from app.services.path_resolver import PathResolutionError, session_export_dir
from app.services.runtime_defaults import docker_public_base_url, is_docker_runtime
from app.services.settings import get_studio_settings

_PROCESS_REGISTRY: dict[int, subprocess.Popen] = {}
_PORT_RANGE_START = 18080
_PORT_RANGE_END = 18120
_LOG_TAIL_CHARS = 12000


def build_run_disabled_message(shared_mode: bool) -> str:
    """Why Build & Run is unavailable -- mode-specific, because the cause is.

    ``build_run_enabled`` defaults on in local mode and off in shared mode,
    so False can now come from either an explicit local-mode operator
    disable or the shared-mode default; a single "shared-mode policy" string
    was accurate for the second case but lied about the first.
    """
    if shared_mode:
        return "Build & Run is disabled by Studio shared-mode policy."
    return (
        "Build & Run is disabled by operator configuration "
        "(EDGEFORGE_STUDIO_BUILD_RUN_ENABLED=false)."
    )


@dataclass
class BuildResult:
    success: bool
    output: str
    command: list[str]
    log_path: str
    summary: str
    jar_path: str | None = None
    route_summary: list[BuildRunRoute] | None = None


@dataclass
class StartResult:
    success: bool
    summary: str
    state: BuildRunState


def ensure_generated_app_path(session: ProjectSession) -> BuildRunState:
    state = session.build_run
    if state.generated_app_path and Path(state.generated_app_path).exists():
        return state

    if session.last_export_path:
        try:
            export_dir = session_export_dir(session)
        except PathResolutionError:
            # Unusable stored path -> no generated app to point at. This runs on
            # the Step-8 page render, so it must not raise.
            return state
        candidate = (export_dir / "generated-app") if export_dir else None
        if candidate is not None and candidate.exists():
            state.generated_app_path = str(candidate)
    return state


def refresh_runtime_state(state: BuildRunState) -> BuildRunState:
    if state.run_status not in {"starting", "running"} or not state.pid:
        return state

    if not _pid_is_alive(state.pid):
        if state.run_status == "starting":
            state.run_status = "run_failed"
            state.run_summary = "Application exited during startup. Check runtime logs."
        else:
            state.run_status = "stopped"
            state.run_summary = "Process is no longer running."
        state.pid = None
        return state

    if state.health_url:
        health = fetch_health(state.health_url)
        if health["ok"]:
            state.run_status = "running"
            state.run_summary = _running_summary(state)
        else:
            state.run_status = "starting"
            state.run_summary = _startup_summary(state.port, state.requested_port or state.port)
    return state


def build_generated_app(app_path: str) -> BuildResult:
    settings = get_studio_settings()
    if not settings.build_run_enabled:
        message = build_run_disabled_message(settings.shared_mode)
        return BuildResult(
            success=False,
            output=message,
            command=[],
            log_path="",
            summary=message,
        )

    app_dir = Path(app_path)
    if not app_dir.exists():
        return BuildResult(
            success=False,
            output="Generated app path not found.",
            command=[],
            log_path="",
            summary="Generated app path not found.",
        )

    log_path = str(_runtime_dir(app_dir) / "build.log")
    cmd = _build_command(app_dir)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(app_dir),
            capture_output=True,
            text=True,
            timeout=get_studio_settings().build_timeout_seconds,
        )
        output = (proc.stdout + proc.stderr).strip()
        Path(log_path).write_text(output, encoding="utf-8")
    except subprocess.TimeoutExpired as exc:
        output = ((exc.stdout or "") + (exc.stderr or "")).strip()
        Path(log_path).write_text(output, encoding="utf-8")
        return BuildResult(
            success=False,
            output=output,
            command=cmd,
            log_path=log_path,
            summary="Build timed out.",
        )
    except FileNotFoundError as exc:
        output = str(exc)
        Path(log_path).write_text(output, encoding="utf-8")
        return BuildResult(
            success=False,
            output=output,
            command=cmd,
            log_path=log_path,
            summary="Build tool not found.",
        )

    if proc.returncode != 0:
        return BuildResult(
            success=False,
            output=output,
            command=cmd,
            log_path=log_path,
            summary="Build failed.",
        )

    jar_path = find_built_jar(app_dir)
    if not jar_path:
        return BuildResult(
            success=False,
            output=output,
            command=cmd,
            log_path=log_path,
            summary="Build succeeded but no runnable jar was found.",
        )

    return BuildResult(
        success=True,
        output=output,
        command=cmd,
        log_path=log_path,
        summary="Build succeeded.",
        jar_path=str(jar_path),
        route_summary=discover_routes(app_dir),
    )


def start_generated_app(state: BuildRunState) -> StartResult:
    settings = get_studio_settings()
    if not settings.build_run_enabled:
        _clear_runtime_binding(state)
        state.run_status = "run_failed"
        state.run_summary = build_run_disabled_message(settings.shared_mode)
        return StartResult(False, state.run_summary, state)

    app_path = state.generated_app_path
    jar_path = state.jar_path
    if not app_path or not Path(app_path).exists():
        _clear_runtime_binding(state)
        state.run_status = "run_failed"
        state.run_summary = "Generated app path not found."
        return StartResult(False, state.run_summary, state)
    if not jar_path or not Path(jar_path).exists():
        _clear_runtime_binding(state)
        state.run_status = "run_failed"
        state.run_summary = "Build the app successfully before running it."
        return StartResult(False, state.run_summary, state)
    if state.pid and _pid_is_alive(state.pid):
        state.run_status = "running"
        state.run_summary = "An app is already running for this session."
        return StartResult(False, state.run_summary, state)

    preferred_port = state.port or _PORT_RANGE_START
    _clear_runtime_binding(state)
    state.requested_port = preferred_port
    try:
        port = choose_port(preferred_port)
    except RuntimeError as exc:
        state.run_status = "run_failed"
        state.run_summary = str(exc)
        return StartResult(False, state.run_summary, state)
    log_path = str(_runtime_dir(Path(app_path)) / "run.log")
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)

    with Path(log_path).open("w", encoding="utf-8") as handle:
        try:
            proc = subprocess.Popen(
                ["java", "-jar", jar_path, f"--server.port={port}", "--appbuilder.demo.enabled=true"],
                cwd=app_path,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
        except FileNotFoundError:
            _clear_runtime_binding(state)
            state.run_status = "run_failed"
            state.run_summary = "Java runtime not found."
            state.run_log_path = log_path
            return StartResult(False, state.run_summary, state)

    _PROCESS_REGISTRY[proc.pid] = proc
    state.pid = proc.pid
    state.port = port
    state.run_log_path = log_path
    state.app_url = f"http://127.0.0.1:{port}"
    state.health_url = f"{state.app_url}/actuator/health"
    state.run_status = "starting"
    state.run_summary = _startup_summary(port, preferred_port)
    return StartResult(True, state.run_summary, state)


def stop_generated_app(state: BuildRunState) -> BuildRunState:
    if not state.pid:
        state.run_status = "stopped"
        state.run_summary = "No managed app is running."
        return state

    stop_process(state.pid)
    state.pid = None
    state.run_status = "stopped"
    state.run_summary = "Application stopped."
    return state


def stop_process(pid: int) -> None:
    proc = _PROCESS_REGISTRY.pop(pid, None)
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
            return
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    try:
        os.killpg(pid, signal.SIGTERM)
        deadline = time.time() + 5
        while time.time() < deadline and _pid_is_alive(pid):
            time.sleep(0.1)
        if _pid_is_alive(pid):
            os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except Exception:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return


def choose_port(preferred_port: int) -> int:
    if _port_is_free(preferred_port):
        return preferred_port
    for port in range(_PORT_RANGE_START, _PORT_RANGE_END + 1):
        if _port_is_free(port):
            return port
    raise RuntimeError("No free local port available in the configured range.")


def fetch_health(health_url: str) -> dict:
    try:
        with urllib.request.urlopen(health_url, timeout=1.0) as response:
            body = response.read().decode("utf-8", errors="replace")
            return {"ok": response.status == 200, "body": body}
    except (urllib.error.URLError, TimeoutError, ValueError):
        return {"ok": False, "body": ""}


def _startup_summary(port: int | None, preferred_port: int | None) -> str:
    if not port:
        return "Application is starting."
    if preferred_port and port != preferred_port:
        return f"Application is starting on port {port}. Preferred port {preferred_port} was busy, so Studio picked the next free local port."
    return f"Application is starting on port {port}."


def _running_summary(state: BuildRunState) -> str:
    if state.port:
        parts = []
        if not _has_ui_surface(state):
            parts.append(f"API-only application is running on port {state.port}.")
        else:
            parts.append(f"Application is running on port {state.port}.")
        if state.requested_port and state.requested_port != state.port:
            parts.append(
                f"Studio picked the next free local port because preferred port {state.requested_port} was busy."
            )
        if not _has_ui_surface(state):
            parts.append("Use the discovered routes below; / may return 404.")
        return " ".join(parts)
    if state.requested_port:
        return f"Application is running. Preferred port was {state.requested_port}."
    return "Application is running."


def _has_homepage_route(routes: list[BuildRunRoute]) -> bool:
    return any(route.method == "GET" and route.path == "/" for route in routes)


def _has_ui_surface(state: BuildRunState) -> bool:
    if _has_homepage_route(state.route_summary):
        return True
    if any(route.controller == "DemoController" for route in state.route_summary):
        return True
    if not state.generated_app_path:
        return False
    app_dir = Path(state.generated_app_path)
    return (app_dir / "src" / "main" / "resources" / "static" / "index.html").exists()


def _clear_runtime_binding(state: BuildRunState) -> None:
    state.pid = None
    state.port = None
    state.app_url = None
    state.health_url = None


def read_log_tail(path: str | None, limit_chars: int = _LOG_TAIL_CHARS) -> str:
    if not path:
        return ""
    log_path = Path(path)
    if not log_path.exists():
        return ""
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    return text[-limit_chars:]


def discover_routes(app_dir: Path) -> list[BuildRunRoute]:
    routes: list[BuildRunRoute] = []
    controller_files = sorted(app_dir.glob("src/main/java/**/*Controller.java"))
    for file_path in controller_files:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        controller = file_path.stem
        base = _extract_class_mapping(content)
        routes.extend(_extract_method_routes(content, base, controller))
    routes.sort(key=lambda route: (route.path, route.method, route.controller or ""))
    return routes


def find_built_jar(app_dir: Path) -> Path | None:
    target = app_dir / "target"
    if not target.exists():
        return None
    jars = [
        path for path in target.glob("*.jar")
        if not path.name.endswith("-sources.jar")
        and not path.name.endswith("-javadoc.jar")
        and not path.name.startswith("original-")
    ]
    if not jars:
        return None
    jars.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return jars[0]


def status_payload(state: BuildRunState) -> dict:
    refreshed = refresh_runtime_state(state)
    health = fetch_health(refreshed.health_url) if refreshed.health_url else {"ok": False, "body": ""}
    log_path = refreshed.run_log_path or refreshed.build_log_path
    app_url, health_url = _display_urls(refreshed)
    return {
        "generated_app_path": refreshed.generated_app_path,
        "build_status": refreshed.build_status,
        "build_summary": refreshed.build_summary,
        "build_log_path": refreshed.build_log_path,
        "run_status": refreshed.run_status,
        "run_summary": refreshed.run_summary,
        "run_log_path": refreshed.run_log_path,
        "app_url": app_url,
        "health_url": health_url,
        "internal_app_url": refreshed.app_url,
        "internal_health_url": refreshed.health_url,
        "health_ok": health["ok"],
        "health_body": health["body"],
        "has_ui_surface": _has_ui_surface(refreshed),
        "port": refreshed.port,
        "pid": refreshed.pid,
        "jar_path": refreshed.jar_path,
        "route_summary": [route.model_dump() for route in refreshed.route_summary],
        "log_tail": read_log_tail(log_path),
    }


def _build_command(app_dir: Path) -> list[str]:
    mvnw = app_dir / "mvnw"
    if mvnw.exists():
        if os.access(mvnw, os.X_OK):
            return [str(mvnw), "clean", "package", "-DskipTests"]
        return ["sh", str(mvnw), "clean", "package", "-DskipTests"]
    return ["mvn", "clean", "package", "-DskipTests"]


def _display_urls(state: BuildRunState) -> tuple[str | None, str | None]:
    if not is_docker_runtime() or not state.port:
        return state.app_url, state.health_url
    base = f"{docker_public_base_url()}/export/generated-app/{state.port}"
    return base, f"{base}/actuator/health"


def _runtime_dir(app_dir: Path) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", app_dir.name.lower()).strip("-") or "generated-app"
    app_key = sha1(str(app_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    root = Path(tempfile.gettempdir()) / "edgeforge_studio_build_run"
    path = root / f"{slug}-{app_key}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _port_is_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _extract_class_mapping(content: str) -> str:
    match = re.search(r"@RequestMapping\((.*?)\)\s*public class", content, re.DOTALL)
    if not match:
        return ""
    return _extract_mapping_path(match.group(1))


def _extract_method_routes(content: str, base_path: str, controller: str) -> list[BuildRunRoute]:
    routes: list[BuildRunRoute] = []
    pattern = re.compile(
        r"@(GetMapping|PostMapping|PutMapping|DeleteMapping|PatchMapping|RequestMapping)(?:\((.*?)\))?\s*public",
        re.DOTALL,
    )
    verb_map = {
        "GetMapping": "GET",
        "PostMapping": "POST",
        "PutMapping": "PUT",
        "DeleteMapping": "DELETE",
        "PatchMapping": "PATCH",
    }
    for annotation, args in pattern.findall(content):
        args = args or ""
        path = _join_paths(base_path, _extract_mapping_path(args))
        methods = [_extract_request_mapping_method(args)] if annotation == "RequestMapping" else [verb_map[annotation]]
        for method in methods:
            if method:
                routes.append(BuildRunRoute(method=method, path=path or "/", controller=controller))
    return routes


def _extract_request_mapping_method(args: str) -> str | None:
    match = re.search(r"RequestMethod\.([A-Z]+)", args)
    if match:
        return match.group(1)
    return None


def _extract_mapping_path(args: str) -> str:
    key_match = re.search(r'(?:value|path)\s*=\s*"([^"]*)"', args)
    if key_match:
        return key_match.group(1)
    bare_match = re.search(r'"([^"]*)"', args)
    if bare_match:
        return bare_match.group(1)
    return ""


def _join_paths(base: str, child: str) -> str:
    if not base:
        return child or "/"
    if not child:
        return base or "/"
    return f"/{base.strip('/')}/{child.strip('/')}"
