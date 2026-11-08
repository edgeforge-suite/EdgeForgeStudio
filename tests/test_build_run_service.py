"""Unit tests for local Build & Run helpers."""


from app.models.project import BuildRunRoute, BuildRunState
from app.services.build_run_service import (
    _running_summary,
    _runtime_dir,
    choose_port,
    discover_routes,
    find_built_jar,
    refresh_runtime_state,
    start_generated_app,
)


def test_discover_routes_reads_controller_mappings(tmp_path):
    controller = tmp_path / "src" / "main" / "java" / "com" / "example" / "adapter" / "inbound" / "CustomerController.java"
    controller.parent.mkdir(parents=True, exist_ok=True)
    controller.write_text(
        """
package com.example.adapter.inbound;

import org.springframework.web.bind.annotation.*;

@RequestMapping("/api/v1/customers")
public class CustomerController {
    @GetMapping("/{customerId}")
    public String getCustomer() { return "ok"; }

    @PostMapping
    public String createCustomer() { return "ok"; }
}
""",
        encoding="utf-8",
    )

    routes = discover_routes(tmp_path)
    assert {(route.method, route.path) for route in routes} == {
        ("GET", "/api/v1/customers/{customerId}"),
        ("POST", "/api/v1/customers"),
    }


def test_find_built_jar_prefers_runnable_jar(tmp_path):
    target = tmp_path / "target"
    target.mkdir(parents=True, exist_ok=True)
    (target / "original-demo.jar").write_text("", encoding="utf-8")
    (target / "demo-sources.jar").write_text("", encoding="utf-8")
    runnable = target / "demo.jar"
    runnable.write_text("", encoding="utf-8")

    jar = find_built_jar(tmp_path)
    assert jar == runnable


def test_runtime_dir_uses_full_app_path_not_just_folder_name(tmp_path):
    app_one = tmp_path / "one" / "generated-app"
    app_two = tmp_path / "two" / "generated-app"
    app_one.mkdir(parents=True, exist_ok=True)
    app_two.mkdir(parents=True, exist_ok=True)

    dir_one = _runtime_dir(app_one)
    dir_two = _runtime_dir(app_two)

    assert dir_one != dir_two
    assert dir_one.name.startswith("generated-app-")
    assert dir_two.name.startswith("generated-app-")


def test_refresh_runtime_state_marks_startup_crash_as_run_failed(monkeypatch):
    state = BuildRunState(
        generated_app_path="/tmp/generated-app",
        run_status="starting",
        run_summary="Application is starting.",
        run_log_path="/tmp/run.log",
        pid=43210,
        app_url="http://127.0.0.1:18080",
        health_url="http://127.0.0.1:18080/actuator/health",
        port=18080,
    )

    monkeypatch.setattr("app.services.build_run_service._pid_is_alive", lambda pid: False)

    refreshed = refresh_runtime_state(state)

    assert refreshed.run_status == "run_failed"
    assert refreshed.run_summary == "Application exited during startup. Check runtime logs."
    assert refreshed.pid is None


def test_refresh_runtime_state_marks_dead_running_process_as_stopped(monkeypatch):
    state = BuildRunState(
        generated_app_path="/tmp/generated-app",
        run_status="running",
        run_summary="Application is running.",
        pid=43210,
    )

    monkeypatch.setattr("app.services.build_run_service._pid_is_alive", lambda pid: False)

    refreshed = refresh_runtime_state(state)

    assert refreshed.run_status == "stopped"
    assert refreshed.run_summary == "Process is no longer running."
    assert refreshed.pid is None


def test_refresh_runtime_state_marks_api_only_app_as_running_with_clear_summary(monkeypatch):
    state = BuildRunState(
        generated_app_path="/tmp/generated-app",
        run_status="starting",
        run_summary="Application is starting.",
        pid=43210,
        port=18080,
        health_url="http://127.0.0.1:18080/actuator/health",
    )
    state.route_summary.append(BuildRunRoute(method="POST", path="/payments"))

    monkeypatch.setattr("app.services.build_run_service._pid_is_alive", lambda pid: True)
    monkeypatch.setattr("app.services.build_run_service.fetch_health", lambda url: {"ok": True, "body": '{"status":"UP"}'})

    refreshed = refresh_runtime_state(state)

    assert refreshed.run_status == "running"
    assert refreshed.run_summary == "API-only application is running on port 18080. Use the discovered routes below; / may return 404."


def test_running_summary_treats_demo_routes_as_ui_surface(tmp_path):
    app_dir = tmp_path / "generated-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    state = BuildRunState(
        generated_app_path=str(app_dir),
        port=18080,
    )
    state.route_summary.append(BuildRunRoute(method="GET", path="/api/demo/entities", controller="DemoController"))

    assert _running_summary(state) == "Application is running on port 18080."


def test_choose_port_uses_next_free_port_when_preferred_is_busy(monkeypatch):
    availability = {18080: False, 18081: True}

    monkeypatch.setattr(
        "app.services.build_run_service._port_is_free",
        lambda port: availability.get(port, False),
    )

    assert choose_port(18080) == 18081


def test_refresh_runtime_state_keeps_port_fallback_hint_while_starting(monkeypatch):
    state = BuildRunState(
        generated_app_path="/tmp/generated-app",
        run_status="starting",
        run_summary="Application is starting on port 18081. Preferred port 18080 was busy, so Studio picked the next free local port.",
        pid=43210,
        requested_port=18080,
        port=18081,
        health_url="http://127.0.0.1:18081/actuator/health",
    )

    monkeypatch.setattr("app.services.build_run_service._pid_is_alive", lambda pid: True)
    monkeypatch.setattr("app.services.build_run_service.fetch_health", lambda url: {"ok": False, "body": ""})

    refreshed = refresh_runtime_state(state)

    assert refreshed.run_status == "starting"
    assert refreshed.run_summary == "Application is starting on port 18081. Preferred port 18080 was busy, so Studio picked the next free local port."


def test_start_generated_app_clears_stale_url_when_run_fails_before_port_selection(monkeypatch, tmp_path):
    app_dir = tmp_path / "generated-app"
    app_dir.mkdir(parents=True, exist_ok=True)
    jar_path = app_dir / "target" / "demo.jar"
    jar_path.parent.mkdir(parents=True, exist_ok=True)
    jar_path.write_text("", encoding="utf-8")

    state = BuildRunState(
        generated_app_path=str(app_dir),
        jar_path=str(jar_path),
        run_status="stopped",
        requested_port=18080,
        port=18080,
        app_url="http://127.0.0.1:18080",
        health_url="http://127.0.0.1:18080/actuator/health",
    )

    monkeypatch.setattr("app.services.build_run_service.choose_port", lambda port: (_ for _ in ()).throw(RuntimeError("No free local port available in the configured range.")))

    result = start_generated_app(state)

    assert result.success is False
    assert state.run_status == "run_failed"
    assert state.app_url is None
    assert state.health_url is None
    assert state.port is None
