"""Shipped container/compose defaults must not expose Studio beyond the host.

Local mode has no auth, by design (CLAUDE.md): it is a single-user tool that
orchestrates local subprocesses. Docker Compose's short port-publish syntax
(``"8083:8083"``) binds to *every* host interface unless a host IP is given,
so the bare form would make an unauthenticated instance reachable from
anywhere that can route to the host -- not just the operator's own machine.

``docker-compose.override.yml`` is deliberately excluded from this repo
(``.git/info/exclude``, "Local Docker settings for this workstation") and is
therefore out of scope here: it is never shipped to anyone else's checkout.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def _studio_port_binding() -> str:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    ports = compose["services"]["studio"]["ports"]
    assert len(ports) == 1, f"expected exactly one published port, got {ports}"
    return str(ports[0])


def test_shipped_compose_port_specifies_a_host_bind_address() -> None:
    """Docker's 2-part short syntax ("8083:8083") binds every host interface;
    a 3-part form ("<host>:8083:8083") is required to scope it at all.

    Splits from the right: the host-bind expression is itself allowed to
    contain a colon (``${VAR:-default}`` shell-style substitution), so a
    naive left-to-right split would cut it in half.
    """
    parts = _studio_port_binding().rsplit(":", 2)
    assert len(parts) == 3, (
        f"published port {':'.join(parts)!r} omits a host bind address -- "
        "Docker's short syntax without one binds every host interface by default"
    )
    assert parts[0] != "0.0.0.0", (
        "published port is explicitly bound to every host interface, which "
        "exposes the no-auth-by-design local mode beyond this machine"
    )


def test_shipped_compose_port_defaults_to_loopback() -> None:
    """Absent an operator override, the bind host must resolve to loopback."""
    host_bind = _studio_port_binding().rsplit(":", 2)[0]

    assert host_bind == "${EDGEFORGE_STUDIO_BIND_HOST:-127.0.0.1}", (
        f"published port host-bind is {host_bind!r} -- it must default to "
        "127.0.0.1 via an overridable env var, not a bare/hardcoded address"
    )


def test_shipped_image_cmd_has_no_reload_flag() -> None:
    """``--reload`` is a file-watcher auto-restart -- the dev inner loop, not
    what the built image should run by default. It stays in docker-compose.yml
    (the bind-mounted dev runtime, checked below) but must not be the image's
    own CMD, which is what anyone running the built image gets.
    """
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    cmd_line = next(line for line in dockerfile.splitlines() if line.startswith("CMD"))

    assert "--reload" not in cmd_line, f"image CMD still carries --reload: {cmd_line}"


def test_compose_reload_is_documented_as_development_only() -> None:
    """``--reload`` is fine in compose (the source tree is bind-mounted here for
    the dev inner loop) but the file must say so, so it doesn't read as an
    oversight next to the image CMD no longer carrying it.
    """
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "--reload" in text, "compose command lost --reload without an explicit decision"
    assert "development-only" in text or "development only" in text, (
        "compose keeps --reload but no longer documents it as development-only"
    )


def test_dockerfile_runs_as_a_non_root_user_with_configurable_ids() -> None:
    """Necessary but NOT sufficient -- this only guards against the directive
    being silently deleted later. It cannot prove writes to bind-mounted host
    directories still succeed: that depends on runtime UID/GID matching, which
    text can't see. There is a prior incident in this codebase of a non-root
    change asserted via string-matching that broke container writes in
    practice (``COPY --chown`` chowns the file, not the WORKDIR).

    The real verification is `docker compose build` + `up` + exercising an
    actual write through the bind mount (see the PR body/commit message for
    the transcript) -- redo that by hand after touching this file, don't trust
    this test alone.
    """
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "ARG APP_UID=" in dockerfile and "ARG APP_GID=" in dockerfile, (
        "no configurable UID/GID build args -- an operator can't match their "
        "host user for the bind-mounted paths in docker-compose.yml"
    )
    assert "\nUSER appuser\n" in dockerfile, "no non-root USER directive"

    user_line = dockerfile.index("\nUSER appuser\n")
    useradd_line = dockerfile.index("useradd ")
    assert 0 < useradd_line < user_line, (
        "USER appuser appears before the user is actually created"
    )
