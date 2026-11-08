"""Security contract for Studio's pinned and bounded OpenAPI fetcher."""

from __future__ import annotations

import ipaddress
import json
import socket
import ssl
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler

import pytest

from app.services.openapi_fetch_guard import (
    MAX_REDIRECTS,
    OpenAPIFetchPolicyError,
    _build_pinned_opener,
    _connect_to_pinned_addresses,
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
    _read_bounded_response,
    _validate_openapi_fetch_target,
    fetch_url_with_policy,
    normalized_openapi_allowed_hosts,
)


class _FakeHeaders:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self._values = {key.lower(): value for key, value in (values or {}).items()}

    def get(self, name: str, default: str | None = None) -> str | None:
        return self._values.get(name.lower(), default)

    def get_content_charset(self, default: str = "utf-8") -> str:
        return default


class _FakeResponse:
    def __init__(
        self,
        body: bytes | str,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = body.encode() if isinstance(body, str) else body
        self.status = status
        self.headers = _FakeHeaders(headers)
        self.offset = 0
        self.read_sizes: list[int] = []
        self.closed = False

    def read(self, size: int) -> bytes:
        assert size >= 0, "bounded fetches must never issue an unbounded read"
        self.read_sizes.append(size)
        chunk = self.body[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def getcode(self) -> int:
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.closed = True


class _FakeSocket:
    def setsockopt(self, *args) -> None:
        return None


class _FakePeerSocket:
    def __init__(self, peer: str) -> None:
        self.peer = peer
        self.closed = False

    def settimeout(self, timeout) -> None:
        return None

    def bind(self, source_address) -> None:
        return None

    def connect(self, sockaddr) -> None:
        return None

    def getpeername(self):
        return self.peer, 443

    def close(self) -> None:
        self.closed = True


class _FakeSSLContext:
    verify_mode = ssl.CERT_REQUIRED
    check_hostname = True
    post_handshake_auth = False

    def __init__(self, wrapped_socket: object) -> None:
        self.wrapped_socket = wrapped_socket
        self.server_hostname: str | None = None

    def wrap_socket(self, sock, *, server_hostname: str):
        self.server_hostname = server_hostname
        return self.wrapped_socket


def _dns(monkeypatch, mapping: dict[str, list[str] | str]) -> list[tuple[str, int]]:
    calls: list[tuple[str, int]] = []

    def fake_getaddrinfo(host: str, port: int, *args, **kwargs):
        calls.append((host, port))
        raw_addresses = mapping[host]
        addresses = [raw_addresses] if isinstance(raw_addresses, str) else raw_addresses
        return [
            (
                socket.AF_INET6 if ":" in address else socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                (address, port),
            )
            for address in addresses
        ]

    monkeypatch.setattr(
        "app.services.openapi_fetch_guard.socket.getaddrinfo",
        fake_getaddrinfo,
    )
    return calls


def _shared_mode(monkeypatch, *, mode: str = "allowlist") -> None:
    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", mode)


def test_public_target_resolves_once_and_opens_only_validated_address(monkeypatch):
    calls = _dns(monkeypatch, {"api.example.com": "93.184.216.34"})
    response = _FakeResponse(json.dumps({"openapi": "3.1.0"}))
    captured = {}

    def fake_open(target, timeout):
        captured["target"] = target
        captured["timeout"] = timeout
        return response

    monkeypatch.setattr("app.services.openapi_fetch_guard._open_url", fake_open)

    result = fetch_url_with_policy("http://api.example.com/openapi.json")

    assert json.loads(result.text)["openapi"] == "3.1.0"
    assert calls == [("api.example.com", 80)]
    assert captured["target"].addresses == (ipaddress.ip_address("93.184.216.34"),)
    assert 0 < captured["timeout"] <= 10
    assert response.closed is True


def test_resolution_connection_and_http_failures_are_browser_safe(monkeypatch):
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard.socket.getaddrinfo",
        lambda *args, **kwargs: (_ for _ in ()).throw(socket.gaierror("secret detail")),
    )
    with pytest.raises(OpenAPIFetchPolicyError) as resolution:
        fetch_url_with_policy("https://unresolved.example/openapi.json")
    assert str(resolution.value) == "OpenAPI URL host could not be resolved."
    assert "secret" not in str(resolution.value)

    _dns(monkeypatch, {"api.example.com": "93.184.216.34"})
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._open_url",
        lambda target, timeout: (_ for _ in ()).throw(OSError("socket detail")),
    )
    with pytest.raises(OpenAPIFetchPolicyError) as connection:
        fetch_url_with_policy("https://api.example.com/openapi.json")
    assert "could not be fetched" in str(connection.value)
    assert "socket detail" not in str(connection.value)

    response = _FakeResponse(b"unavailable", status=503)
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._open_url",
        lambda target, timeout: response,
    )
    with pytest.raises(OpenAPIFetchPolicyError, match="failed with HTTP 503"):
        fetch_url_with_policy("https://api.example.com/openapi.json")
    assert response.closed is True

    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._open_url",
        lambda target, timeout: (_ for _ in ()).throw(
            URLError(TimeoutError("socket timed out"))
        ),
    )
    with pytest.raises(OpenAPIFetchPolicyError, match="configured timeout"):
        fetch_url_with_policy("https://api.example.com/openapi.json")


def test_invalid_port_fails_before_resolution(monkeypatch):
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard.socket.getaddrinfo",
        lambda *args, **kwargs: pytest.fail("invalid port reached DNS"),
    )

    with pytest.raises(OpenAPIFetchPolicyError, match="port is invalid"):
        _validate_openapi_fetch_target("https://api.example.com:99999/openapi.json")


def test_pinned_http_connection_uses_validated_address_and_original_host(monkeypatch):
    approved = ipaddress.ip_address("93.184.216.34")
    captured = {}
    sentinel = object()

    def fake_connect(addresses, port, timeout, source_address):
        captured.update(
            addresses=addresses,
            port=port,
            timeout=timeout,
            source_address=source_address,
        )
        return sentinel

    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._connect_to_pinned_addresses",
        fake_connect,
    )
    connection = _PinnedHTTPConnection(
        "api.example.com",
        8080,
        pinned_addresses=(approved,),
    )

    assert connection._create_connection(("203.0.113.8", 8080), 10, None) is sentinel
    assert captured["addresses"] == (approved,)
    assert connection.host == "api.example.com"
    connection.putrequest("GET", "/openapi.json")
    assert b"Host: api.example.com:8080" in connection._buffer


def test_pinned_https_connection_keeps_original_host_for_sni(monkeypatch):
    approved = ipaddress.ip_address("93.184.216.34")
    raw_socket = _FakeSocket()
    wrapped_socket = object()
    context = _FakeSSLContext(wrapped_socket)
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._connect_to_pinned_addresses",
        lambda *args, **kwargs: raw_socket,
    )
    connection = _PinnedHTTPSConnection(
        "api.example.com",
        443,
        context=context,
        pinned_addresses=(approved,),
    )

    connection.connect()

    assert connection.sock is wrapped_socket
    assert context.server_hostname == "api.example.com"


def test_pinned_connection_rejects_actual_peer_mismatch(monkeypatch):
    approved = ipaddress.ip_address("93.184.216.34")
    fake_socket = _FakePeerSocket("10.20.30.40")
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard.socket.socket",
        lambda *args, **kwargs: fake_socket,
    )

    with pytest.raises(OpenAPIFetchPolicyError, match="peer did not match"):
        _connect_to_pinned_addresses((approved,), 443, 10, None)

    assert fake_socket.closed is True


def test_pinned_opener_disables_all_ambient_proxies(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("ALL_PROXY", "socks5://proxy.example:1080")
    target = _validate_openapi_fetch_target("https://93.184.216.34/openapi.json")
    handlers: list[object] = []
    sentinel = object()

    def fake_build_opener(*items):
        handlers.extend(items)
        return sentinel

    monkeypatch.setattr(
        "app.services.openapi_fetch_guard.build_opener",
        fake_build_opener,
    )

    assert _build_pinned_opener(target) is sentinel
    proxy_handlers = [item for item in handlers if isinstance(item, ProxyHandler)]
    assert len(proxy_handlers) == 1
    assert proxy_handlers[0].proxies == {}


@pytest.mark.parametrize("address", ["10.20.30.40", "fd12:3456::40"])
def test_shared_exact_allowlist_accepts_private_service_address(monkeypatch, address):
    _shared_mode(monkeypatch)
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        "api.internal.example",
    )
    _dns(monkeypatch, {"api.internal.example": address})

    target = _validate_openapi_fetch_target(
        "https://api.internal.example/openapi.json"
    )

    assert target.addresses == (ipaddress.ip_address(address),)


@pytest.mark.parametrize("address", ["10.20.30.40", "fd12:3456::40"])
def test_non_allowlisted_private_service_address_fails(monkeypatch, address):
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "open")
    _dns(monkeypatch, {"api.internal.example": address})

    with pytest.raises(OpenAPIFetchPolicyError, match="host is not allowed"):
        _validate_openapi_fetch_target("https://api.internal.example/openapi.json")


def test_local_allowlist_mode_requires_exact_host_even_for_public_target(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "allowlist")
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        "approved.example",
    )
    _dns(
        monkeypatch,
        {
            "approved.example": "93.184.216.34",
            "other.example": "93.184.216.35",
        },
    )

    target = _validate_openapi_fetch_target(
        "https://approved.example/openapi.json"
    )
    assert target.addresses == (ipaddress.ip_address("93.184.216.34"),)

    with pytest.raises(OpenAPIFetchPolicyError, match="host is not allowed"):
        _validate_openapi_fetch_target("https://other.example/openapi.json")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_shared_loopback_fails_even_when_allowlisted(monkeypatch, host):
    _shared_mode(monkeypatch)
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", host)
    if host == "localhost":
        _dns(monkeypatch, {host: ["127.0.0.1", "::1"]})
    rendered = f"[{host}]" if ":" in host else host

    with pytest.raises(OpenAPIFetchPolicyError, match="host is not allowed"):
        _validate_openapi_fetch_target(f"http://{rendered}:8080/openapi.json")


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "::1"])
def test_local_loopback_targets_remain_supported_and_pinned(monkeypatch, host):
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "open")
    if host == "localhost":
        _dns(monkeypatch, {host: ["127.0.0.1", "::1"]})
    rendered = f"[{host}]" if ":" in host else host

    target = _validate_openapi_fetch_target(
        f"http://{rendered}:8080/openapi.json"
    )

    assert all(address.is_loopback for address in target.addresses)


def test_local_hostname_resolving_to_loopback_requires_exact_allowlist(monkeypatch):
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "open")
    _dns(monkeypatch, {"dev-api.local": "127.0.0.1"})

    with pytest.raises(OpenAPIFetchPolicyError, match="host is not allowed"):
        _validate_openapi_fetch_target("http://dev-api.local:8080/openapi.json")

    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        "dev-api.local",
    )
    target = _validate_openapi_fetch_target(
        "http://dev-api.local:8080/openapi.json"
    )
    assert target.addresses == (ipaddress.ip_address("127.0.0.1"),)


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://[fd00:ec2::254]/latest/meta-data",
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://[::ffff:169.254.169.254]/latest/meta-data",
        "http://100.64.0.1/openapi.json",
    ],
)
def test_metadata_and_special_targets_are_non_bypassable(monkeypatch, url):
    host = url.split("//", 1)[1].split("/", 1)[0].strip("[]")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", host)

    with pytest.raises(OpenAPIFetchPolicyError, match="host is not allowed"):
        _validate_openapi_fetch_target(url)


def test_mixed_dns_result_rejects_whole_target(monkeypatch):
    _dns(
        monkeypatch,
        {"api.example.com": ["93.184.216.34", "169.254.169.254"]},
    )

    with pytest.raises(OpenAPIFetchPolicyError, match="host is not allowed"):
        _validate_openapi_fetch_target("https://api.example.com/openapi.json")


def test_accepted_dns_addresses_are_sorted_before_connection(monkeypatch):
    _dns(
        monkeypatch,
        {"api.example.com": ["2001:4860:4860::8888", "93.184.216.34"]},
    )

    target = _validate_openapi_fetch_target(
        "https://api.example.com/openapi.json"
    )

    assert target.addresses == (
        ipaddress.ip_address("93.184.216.34"),
        ipaddress.ip_address("2001:4860:4860::8888"),
    )


def test_redirects_resolve_and_pin_each_hop_independently(monkeypatch):
    calls = _dns(
        monkeypatch,
        {
            "api.example.com": "93.184.216.34",
            "cdn.example.com": "93.184.216.35",
        },
    )
    opened = []

    def fake_open(target, timeout):
        opened.append((target.host, target.addresses))
        if target.host == "api.example.com":
            return _FakeResponse(
                b"",
                status=302,
                headers={"Location": "https://cdn.example.com/openapi.json"},
            )
        return _FakeResponse(json.dumps({"openapi": "3.1.0"}))

    monkeypatch.setattr("app.services.openapi_fetch_guard._open_url", fake_open)

    result = fetch_url_with_policy("https://api.example.com/start")

    assert json.loads(result.text)["openapi"] == "3.1.0"
    assert calls == [("api.example.com", 443), ("cdn.example.com", 443)]
    assert opened == [
        ("api.example.com", (ipaddress.ip_address("93.184.216.34"),)),
        ("cdn.example.com", (ipaddress.ip_address("93.184.216.35"),)),
    ]


def test_redirect_hops_share_one_monotonic_deadline(monkeypatch):
    clock = [0.0]
    timeouts: list[float] = []

    def fake_open(target, timeout):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            clock[0] += 3
            return _FakeResponse(
                b"",
                status=302,
                headers={"Location": "https://93.184.216.35/openapi.json"},
            )
        return _FakeResponse(b'{"openapi":"3.1.0"}')

    monkeypatch.setattr(
        "app.services.openapi_fetch_guard.time.monotonic",
        lambda: clock[0],
    )
    monkeypatch.setattr("app.services.openapi_fetch_guard._open_url", fake_open)

    result = fetch_url_with_policy(
        "https://93.184.216.34/openapi.json",
        timeout=10,
    )

    assert json.loads(result.text)["openapi"] == "3.1.0"
    assert timeouts == pytest.approx([10, 7])


def test_redirect_to_disallowed_private_target_fails_before_second_open(monkeypatch):
    _dns(
        monkeypatch,
        {
            "api.example.com": "93.184.216.34",
            "private.example.com": "10.20.30.40",
        },
    )
    opened: list[str] = []

    def fake_open(target, timeout):
        opened.append(target.host)
        return _FakeResponse(
            b"",
            status=302,
            headers={"Location": "http://private.example.com/openapi.json"},
        )

    monkeypatch.setattr("app.services.openapi_fetch_guard._open_url", fake_open)

    with pytest.raises(OpenAPIFetchPolicyError, match="redirect target is not allowed"):
        fetch_url_with_policy("https://api.example.com/openapi.json")

    assert opened == ["api.example.com"]


def test_redirect_without_location_and_excess_depth_fail_closed(monkeypatch):
    _dns(monkeypatch, {"api.example.com": "93.184.216.34"})
    missing = _FakeResponse(b"", status=302)
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._open_url",
        lambda target, timeout: missing,
    )
    with pytest.raises(OpenAPIFetchPolicyError, match="did not include a target"):
        fetch_url_with_policy("https://api.example.com/openapi.json")
    assert missing.closed is True

    responses: list[_FakeResponse] = []

    def loop(target, timeout):
        response = _FakeResponse(
            b"",
            status=302,
            headers={"Location": "/openapi.json"},
        )
        responses.append(response)
        return response

    monkeypatch.setattr("app.services.openapi_fetch_guard._open_url", loop)
    with pytest.raises(OpenAPIFetchPolicyError, match="redirect limit"):
        fetch_url_with_policy("https://api.example.com/openapi.json")
    assert len(responses) == MAX_REDIRECTS + 1
    assert all(response.closed for response in responses)


def test_excessive_content_length_fails_before_body_read_and_closes(monkeypatch):
    _dns(monkeypatch, {"api.example.com": "93.184.216.34"})
    response = _FakeResponse(
        b"ignored",
        headers={"Content-Length": "11"},
    )
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._open_url",
        lambda target, timeout: response,
    )

    with pytest.raises(OpenAPIFetchPolicyError, match="maximum response size"):
        fetch_url_with_policy(
            "https://api.example.com/openapi.json",
            max_bytes=10,
        )

    assert response.read_sizes == []
    assert response.closed is True


def test_unknown_length_body_stops_at_first_overflow_without_partial_result(monkeypatch):
    _dns(monkeypatch, {"api.example.com": "93.184.216.34"})
    response = _FakeResponse(b"x" * 70_001)
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._open_url",
        lambda target, timeout: response,
    )

    with pytest.raises(OpenAPIFetchPolicyError, match="maximum response size"):
        fetch_url_with_policy(
            "https://api.example.com/openapi.json",
            max_bytes=70_000,
        )

    assert response.read_sizes == [64 * 1024, 4_465]
    assert response.offset == 70_001
    assert response.closed is True


def test_one_deadline_stops_a_slow_trickle_response(monkeypatch):
    clock = [0.0]

    class DeadlineSocket:
        timeout = 0.0

        def settimeout(self, timeout: float) -> None:
            self.timeout = timeout

    class Raw:
        _sock = DeadlineSocket()

    class Buffered:
        raw = Raw()

    class TrickleResponse(_FakeResponse):
        fp = Buffered()

        def read(self, size: int) -> bytes:
            pytest.fail("bounded network responses must use single-receive read1()")

        def read1(self, size: int) -> bytes:
            delay = 0.6
            if delay > self.fp.raw._sock.timeout:
                clock[0] += self.fp.raw._sock.timeout
                raise TimeoutError("deadline reached")
            clock[0] += delay
            return b"x"

    response = TrickleResponse(b"xxx", headers={"Content-Length": "3"})
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard.time.monotonic",
        lambda: clock[0],
    )
    monkeypatch.setattr(
        "app.services.openapi_fetch_guard._open_url",
        lambda target, timeout: response,
    )

    with pytest.raises(OpenAPIFetchPolicyError, match="configured timeout"):
        fetch_url_with_policy(
            "http://127.0.0.1:8080/openapi.json",
            timeout=1,
        )

    assert clock[0] == pytest.approx(1)
    assert response.closed is True


def test_dns_resolution_is_inside_the_fetch_deadline(monkeypatch):
    release = threading.Event()
    finished = threading.Event()

    def blocked_resolution(*args, **kwargs):
        try:
            release.wait(timeout=2)
            return []
        finally:
            finished.set()

    monkeypatch.setattr(
        "app.services.openapi_fetch_guard.socket.getaddrinfo",
        blocked_resolution,
    )
    started = time.monotonic()
    try:
        with pytest.raises(OpenAPIFetchPolicyError, match="configured timeout"):
            fetch_url_with_policy(
                "https://slow-dns.example/openapi.json",
                timeout=0.05,
            )
    finally:
        release.set()
        assert finished.wait(timeout=1)

    assert time.monotonic() - started < 0.5


def test_exactly_at_limit_body_succeeds_incrementally():
    response = _FakeResponse(b"1234567890", headers={"Content-Length": "10"})

    assert _read_bounded_response(response, max_bytes=10) == b"1234567890"
    assert all(size >= 0 for size in response.read_sizes)


def test_allowlist_normalization_is_sorted_and_deterministic(monkeypatch):
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        " B.example.,a.example,b.example,A.EXAMPLE ",
    )

    assert normalized_openapi_allowed_hosts() == ("a.example", "b.example")
