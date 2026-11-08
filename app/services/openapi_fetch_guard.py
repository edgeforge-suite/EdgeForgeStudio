"""Address-pinned, response-bounded OpenAPI URL fetching for Studio."""

from __future__ import annotations

import ipaddress
import os
import queue
import socket
import threading
import time
from dataclasses import dataclass
from functools import partial
from http.client import HTTPConnection, HTTPSConnection
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import (
    HTTPHandler,
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    build_opener,
)

from app.services.settings import StudioSettings, get_studio_settings

ALLOWED_HOSTS_ENV = "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS"
ENGINE_ALLOWED_HOSTS_ENV = "EDGEFORGE_OPENAPI_FETCH_ALLOWED_HOSTS"
ALLOWED_SCHEMES = {"http", "https"}
DEFAULT_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
READ_CHUNK_BYTES = 64 * 1024
REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}
BLOCKED_METADATA_HOSTS = {"metadata.google.internal"}
BLOCKED_METADATA_ADDRESSES = {
    ipaddress.ip_address("169.254.169.254"),
    ipaddress.ip_address("fd00:ec2::254"),
}
PRIVATE_SERVICE_NETWORKS = (
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
)
IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
_DNS_RESOLUTION_SLOTS = threading.BoundedSemaphore(4)


class OpenAPIFetchPolicyError(ValueError):
    """Raised when a user-provided OpenAPI URL violates Studio fetch policy."""


@dataclass(frozen=True)
class _ValidatedOpenAPIURL:
    url: str
    host: str
    port: int
    addresses: tuple[IPAddress, ...]


@dataclass(frozen=True)
class OpenAPIFetchResponse:
    """The fully bounded and decoded response consumed by OpenAPI parsing."""

    text: str
    status_code: int


@dataclass(frozen=True)
class _FetchDeadline:
    expires_at: float

    @classmethod
    def after(cls, timeout_seconds: int | float) -> _FetchDeadline:
        return cls(time.monotonic() + max(0.0, float(timeout_seconds)))

    def remaining(self) -> float:
        remaining = self.expires_at - time.monotonic()
        if remaining <= 0:
            raise OpenAPIFetchPolicyError(
                "OpenAPI URL fetch exceeded the configured timeout."
            )
        return remaining


class _NoRedirectHandler(HTTPRedirectHandler):
    """Expose redirects to the policy loop instead of following implicitly."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _connect_to_pinned_addresses(
    addresses: tuple[IPAddress, ...],
    port: int,
    timeout,
    source_address,
):
    """Connect only to numeric addresses approved by this redirect hop."""
    last_error: OSError | None = None
    connect_deadline = (
        None
        if timeout is socket._GLOBAL_DEFAULT_TIMEOUT
        else _FetchDeadline.after(timeout)
    )
    for address in addresses:
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        sock = socket.socket(family, socket.SOCK_STREAM)
        try:
            if connect_deadline is not None:
                sock.settimeout(connect_deadline.remaining())
            if source_address:
                sock.bind(source_address)
            sockaddr = (
                (str(address), port, 0, 0)
                if address.version == 6
                else (str(address), port)
            )
            sock.connect(sockaddr)
            peer = ipaddress.ip_address(str(sock.getpeername()[0]).split("%", 1)[0])
            if peer != address:
                raise OpenAPIFetchPolicyError(
                    "OpenAPI connection peer did not match the validated address."
                )
            return sock
        except OpenAPIFetchPolicyError:
            sock.close()
            raise
        except OSError as exc:
            last_error = exc
            sock.close()
    if last_error is not None:
        raise last_error
    raise OSError("OpenAPI URL had no validated connection address.")


class _PinnedHTTPConnection(HTTPConnection):
    """HTTP connection pinned to policy-approved addresses."""

    def __init__(
        self,
        host,
        port=None,
        *,
        pinned_addresses: tuple[IPAddress, ...],
        **kwargs,
    ):
        super().__init__(host, port, **kwargs)
        self._pinned_addresses = pinned_addresses
        self._create_connection = self._create_pinned_connection

    def _create_pinned_connection(self, _address, timeout, source_address):
        return _connect_to_pinned_addresses(
            self._pinned_addresses,
            self.port,
            timeout,
            source_address,
        )


class _PinnedHTTPSConnection(HTTPSConnection):
    """HTTPS connection pinned while retaining original-host TLS checks."""

    def __init__(
        self,
        host,
        port=None,
        *,
        pinned_addresses: tuple[IPAddress, ...],
        **kwargs,
    ):
        super().__init__(host, port, **kwargs)
        self._pinned_addresses = pinned_addresses
        self._create_connection = self._create_pinned_connection

    def _create_pinned_connection(self, _address, timeout, source_address):
        return _connect_to_pinned_addresses(
            self._pinned_addresses,
            self.port,
            timeout,
            source_address,
        )


class _PinnedHTTPHandler(HTTPHandler):
    def __init__(self, addresses: tuple[IPAddress, ...]) -> None:
        super().__init__()
        self._addresses = addresses

    def http_open(self, req):
        connection = partial(
            _PinnedHTTPConnection,
            pinned_addresses=self._addresses,
        )
        return self.do_open(connection, req)


class _PinnedHTTPSHandler(HTTPSHandler):
    def __init__(self, addresses: tuple[IPAddress, ...]) -> None:
        super().__init__()
        self._addresses = addresses

    def https_open(self, req):
        connection = partial(
            _PinnedHTTPSConnection,
            pinned_addresses=self._addresses,
        )
        return self.do_open(
            connection,
            req,
            context=self._context,
            check_hostname=self._check_hostname,
        )


def _normalized_host(host: str) -> str:
    return host.strip().strip("[]").rstrip(".").lower()


def normalized_openapi_allowed_hosts() -> tuple[str, ...]:
    """Return Studio's authoritative allowlist in deterministic env form."""
    raw = os.getenv(ALLOWED_HOSTS_ENV, "")
    return tuple(
        sorted(
            {
                normalized
                for part in raw.split(",")
                if (normalized := _normalized_host(part))
            }
        )
    )


def _is_private_service_address(address: IPAddress) -> bool:
    return any(address in network for network in PRIVATE_SERVICE_NETWORKS)


def _literal_address(host: str) -> IPAddress | None:
    ip_host = host.split("%25", 1)[0].split("%", 1)[0]
    try:
        return ipaddress.ip_address(ip_host)
    except ValueError:
        return None


def _getaddrinfo_before_deadline(
    host: str,
    port: int,
    *,
    deadline: _FetchDeadline,
):
    """Bound blocking system resolution without leaving unbounded worker growth."""
    if not _DNS_RESOLUTION_SLOTS.acquire(timeout=deadline.remaining()):
        raise OpenAPIFetchPolicyError(
            "OpenAPI URL fetch exceeded the configured timeout."
        )

    result_queue: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def resolve() -> None:
        try:
            result_queue.put((True, socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        except Exception as exc:  # handed back to the requesting thread
            result_queue.put((False, exc))
        finally:
            _DNS_RESOLUTION_SLOTS.release()

    threading.Thread(target=resolve, daemon=True).start()
    try:
        succeeded, value = result_queue.get(timeout=deadline.remaining())
    except queue.Empty as exc:
        raise OpenAPIFetchPolicyError(
            "OpenAPI URL fetch exceeded the configured timeout."
        ) from exc
    if succeeded:
        return value
    if isinstance(value, BaseException):
        raise value
    raise RuntimeError("OpenAPI DNS resolution returned an invalid result.")


def _resolved_addresses(
    host: str,
    port: int,
    *,
    deadline: _FetchDeadline,
) -> set[IPAddress]:
    try:
        results = _getaddrinfo_before_deadline(host, port, deadline=deadline)
    except socket.gaierror as exc:
        raise OpenAPIFetchPolicyError(
            "OpenAPI URL host could not be resolved."
        ) from exc

    addresses: set[IPAddress] = set()
    for result in results:
        sockaddr = result[4]
        if not sockaddr:
            continue
        try:
            addresses.add(ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0]))
        except ValueError as exc:
            raise OpenAPIFetchPolicyError(
                "OpenAPI URL host is not allowed by Studio fetch policy."
            ) from exc
    if not addresses:
        raise OpenAPIFetchPolicyError("OpenAPI URL host could not be resolved.")
    return addresses


def _address_is_allowed(
    address: IPAddress,
    *,
    host: str,
    allowlisted: bool,
    settings: StudioSettings,
) -> bool:
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        return False
    if address in BLOCKED_METADATA_ADDRESSES:
        return False
    if address.is_loopback:
        if settings.shared_mode:
            return False
        literal = _literal_address(host)
        return host == "localhost" or bool(literal and literal.is_loopback) or allowlisted
    if (
        address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        return False
    if _is_private_service_address(address):
        return allowlisted
    return address.is_global


def _validate_openapi_fetch_target(
    url: str,
    *,
    settings: StudioSettings | None = None,
    deadline: _FetchDeadline | None = None,
) -> _ValidatedOpenAPIURL:
    settings = settings or get_studio_settings()
    deadline = deadline or _FetchDeadline.after(
        settings.openapi_fetch_timeout_seconds
    )
    if settings.openapi_fetch_mode == "disabled":
        raise OpenAPIFetchPolicyError("OpenAPI URL fetch is disabled by Studio policy.")

    candidate = (url or "").strip()
    parsed = urlparse(candidate)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise OpenAPIFetchPolicyError("OpenAPI URL must use http or https.")
    if not parsed.hostname:
        raise OpenAPIFetchPolicyError("OpenAPI URL must include a hostname.")
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise OpenAPIFetchPolicyError("OpenAPI URL port is invalid.") from exc

    host = _normalized_host(parsed.hostname)
    allowed_hosts = set(normalized_openapi_allowed_hosts())
    allowlisted = host in allowed_hosts
    if host in BLOCKED_METADATA_HOSTS:
        raise OpenAPIFetchPolicyError(
            "OpenAPI URL host is not allowed by Studio fetch policy."
        )
    if settings.openapi_fetch_mode == "allowlist" and not allowlisted:
        raise OpenAPIFetchPolicyError(
            "OpenAPI URL host is not allowed by Studio fetch policy."
        )

    literal = _literal_address(host)
    if literal is None:
        if ":" in host:
            raise OpenAPIFetchPolicyError(
                "OpenAPI URL host is not allowed by Studio fetch policy."
            )
        addresses = _resolved_addresses(host, port, deadline=deadline)
    else:
        addresses = {literal}

    if any(
        not _address_is_allowed(
            address,
            host=host,
            allowlisted=allowlisted,
            settings=settings,
        )
        for address in addresses
    ):
        raise OpenAPIFetchPolicyError(
            "OpenAPI URL host is not allowed by Studio fetch policy."
        )

    ordered_addresses = tuple(
        sorted(addresses, key=lambda item: (item.version, int(item)))
    )
    return _ValidatedOpenAPIURL(
        url=candidate,
        host=host,
        port=port,
        addresses=ordered_addresses,
    )


def validate_openapi_fetch_url(
    url: str,
    *,
    settings: StudioSettings | None = None,
) -> str:
    """Validate and resolve an OpenAPI URL without opening a connection."""
    return _validate_openapi_fetch_target(url, settings=settings).url


def _build_pinned_opener(target: _ValidatedOpenAPIURL):
    return build_opener(
        ProxyHandler({}),
        _NoRedirectHandler(),
        _PinnedHTTPHandler(target.addresses),
        _PinnedHTTPSHandler(target.addresses),
    )


def _open_url(target: _ValidatedOpenAPIURL, timeout: int | float):
    return _build_pinned_opener(target).open(target.url, timeout=timeout)


def _redirect_target(
    current_target: _ValidatedOpenAPIURL,
    response,
    *,
    settings: StudioSettings,
    deadline: _FetchDeadline,
) -> _ValidatedOpenAPIURL:
    location = response.headers.get("Location")
    if not location:
        raise OpenAPIFetchPolicyError(
            "OpenAPI URL redirect response did not include a target."
        )
    try:
        return _validate_openapi_fetch_target(
            urljoin(current_target.url, location),
            settings=settings,
            deadline=deadline,
        )
    except OpenAPIFetchPolicyError as exc:
        raise OpenAPIFetchPolicyError(
            "OpenAPI URL redirect target is not allowed."
        ) from exc


def _response_size_error(max_bytes: int) -> OpenAPIFetchPolicyError:
    return OpenAPIFetchPolicyError(
        f"OpenAPI URL response exceeded the maximum response size of {max_bytes} bytes."
    )


def _set_response_socket_timeout(response, timeout: float) -> None:
    """Keep each body read within the one fetch-wide deadline."""
    fp = getattr(response, "fp", None)
    raw = getattr(fp, "raw", None)
    sock = getattr(raw, "_sock", None)
    if sock is not None:
        sock.settimeout(timeout)


def _read_bounded_response(
    response,
    *,
    max_bytes: int,
    deadline: _FetchDeadline | None = None,
) -> bytes:
    content_length = response.headers.get("Content-Length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError:
            declared_length = None
        if declared_length is not None and declared_length > max_bytes:
            raise _response_size_error(max_bytes)

    payload = bytearray()
    while True:
        if deadline is not None:
            _set_response_socket_timeout(response, deadline.remaining())
        remaining_with_probe = max_bytes - len(payload) + 1
        try:
            reader = getattr(response, "read1", response.read)
            chunk = reader(min(READ_CHUNK_BYTES, remaining_with_probe))
        except TimeoutError as exc:
            raise OpenAPIFetchPolicyError(
                "OpenAPI URL fetch exceeded the configured timeout."
            ) from exc
        if not chunk:
            return bytes(payload)
        if len(payload) + len(chunk) > max_bytes:
            raise _response_size_error(max_bytes)
        payload.extend(chunk)


def fetch_url_with_policy(
    url: str,
    *,
    timeout: int | float | None = None,
    max_bytes: int | None = None,
    settings: StudioSettings | None = None,
) -> OpenAPIFetchResponse:
    """Fetch one bounded response after pinning every redirect hop."""
    settings = settings or get_studio_settings()
    timeout = (
        settings.openapi_fetch_timeout_seconds if timeout is None else timeout
    )
    max_bytes = settings.openapi_fetch_max_bytes if max_bytes is None else max_bytes
    deadline = _FetchDeadline.after(timeout)
    current_target = _validate_openapi_fetch_target(
        url,
        settings=settings,
        deadline=deadline,
    )

    for _redirect_count in range(MAX_REDIRECTS + 1):
        try:
            response = _open_url(current_target, timeout=deadline.remaining())
        except HTTPError as exc:
            if exc.code not in REDIRECT_STATUS_CODES:
                exc.close()
                raise OpenAPIFetchPolicyError(
                    f"OpenAPI URL fetch failed with HTTP {exc.code}."
                ) from exc
            response = exc
        except TimeoutError as exc:
            raise OpenAPIFetchPolicyError(
                "OpenAPI URL fetch exceeded the configured timeout."
            ) from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise OpenAPIFetchPolicyError(
                    "OpenAPI URL fetch exceeded the configured timeout."
                ) from exc
            raise OpenAPIFetchPolicyError(
                "OpenAPI URL could not be fetched. Verify the URL is reachable from this machine."
            ) from exc
        except OSError as exc:
            raise OpenAPIFetchPolicyError(
                "OpenAPI URL could not be fetched. Verify the URL is reachable from this machine."
            ) from exc

        with response:
            deadline.remaining()
            status_value = getattr(response, "status", None)
            status = int(
                status_value if status_value is not None else response.getcode()
            )
            if status in REDIRECT_STATUS_CODES:
                if _redirect_count >= MAX_REDIRECTS:
                    raise OpenAPIFetchPolicyError(
                        "OpenAPI URL exceeded redirect limit."
                    )
                current_target = _redirect_target(
                    current_target,
                    response,
                    settings=settings,
                    deadline=deadline,
                )
                continue
            if status < 200 or status >= 300:
                raise OpenAPIFetchPolicyError(
                    f"OpenAPI URL fetch failed with HTTP {status}."
                )
            payload = _read_bounded_response(
                response,
                max_bytes=max_bytes,
                deadline=deadline,
            )
            charset = response.headers.get_content_charset("utf-8")
            return OpenAPIFetchResponse(
                text=payload.decode(charset, errors="replace"),
                status_code=status,
            )

    raise OpenAPIFetchPolicyError("OpenAPI URL exceeded redirect limit.")
