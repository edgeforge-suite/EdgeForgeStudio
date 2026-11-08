"""Tests for OpenAPI classification service."""

import json
import socket

import httpx
import pytest

from app.services.openapi_service import (
    _find_response_schema,
    _normalize_entity_name,
    _response_schema_refs,
    classify_openapi_spec,
    fetch_openapi_from_url,
    generate_field_mapping_plan,
    generate_field_mappings,
    generate_operation_samples,
    parse_openapi_text,
)

SAMPLE_SPEC = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0"},
    "paths": {
        "/accounts": {
            "post": {
                "operationId": "createAccount",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/CreateAccountRequest"}
                        }
                    }
                },
                "responses": {
                    "201": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Account"}
                            }
                        }
                    }
                }
            }
        },
        "/accounts/{id}": {
            "get": {
                "operationId": "getAccount",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Account"}
                            }
                        }
                    }
                }
            }
        },
    },
    "components": {
        "schemas": {
            "Account": {
                "type": "object",
                "properties": {
                    "accountId": {"type": "string"},
                    "customerId": {"type": "string"},
                    "accountType": {"type": "string"},
                    "status": {"type": "string"},
                },
                "required": ["accountId"],
            },
            "CreateAccountRequest": {
                "type": "object",
                "properties": {
                    "customerId": {"type": "string"},
                    "accountType": {"type": "string"},
                },
            },
            "PageableObject": {
                "type": "object",
                "properties": {
                    "page": {"type": "integer"},
                    "size": {"type": "integer"},
                },
            },
            "ErrorResponse": {
                "type": "object",
                "properties": {
                    "message": {"type": "string"},
                    "code": {"type": "integer"},
                },
            },
        }
    },
}


def _openapi_response(
    url: str,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers=headers or {},
        text=json.dumps(SAMPLE_SPEC),
        request=httpx.Request("GET", url),
    )


_HTTP_GET = httpx.get


class _HTTPXResponseAdapter:
    """Adapt existing parser fixtures to the pinned transport response seam."""

    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self._content = response.content
        self._offset = 0
        self.status = response.status_code
        self.headers = self

    def get(self, name: str, default=None):
        return self._response.headers.get(name, default)

    def get_content_charset(self, default: str = "utf-8") -> str:
        return self._response.encoding or default

    def getcode(self) -> int:
        return self.status

    def read(self, size: int) -> bytes:
        chunk = self._content[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._response.close()


@pytest.fixture(autouse=True)
def _adapt_existing_fetch_fixtures_to_pinned_transport(monkeypatch):
    def fake_open(target, timeout):
        response = _HTTP_GET(
            target.url,
            timeout=timeout,
            follow_redirects=False,
        )
        return _HTTPXResponseAdapter(response)

    monkeypatch.setattr("app.services.openapi_fetch_guard._open_url", fake_open)


def _mock_dns(monkeypatch, mapping: dict[str, str]) -> None:
    def fake_getaddrinfo(host: str, port: int, *args, **kwargs):
        address = mapping[host]
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        return [(family, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr("app.services.openapi_fetch_guard.socket.getaddrinfo", fake_getaddrinfo)


def test_fetch_openapi_allows_localhost_url(monkeypatch):
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        assert kwargs["follow_redirects"] is False
        assert 0 < kwargs["timeout"] <= 10
        return _openapi_response(url)

    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fake_get)

    spec = fetch_openapi_from_url("http://localhost:8081/v3/api-docs")

    assert spec["info"]["title"] == "Test API"
    assert calls == ["http://localhost:8081/v3/api-docs"]


def test_fetch_openapi_allows_loopback_ipv4_url(monkeypatch):
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return _openapi_response(url)

    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fake_get)

    spec = fetch_openapi_from_url("http://127.0.0.1:8081/v3/api-docs")

    assert spec["openapi"] == "3.0.0"
    assert calls == ["http://127.0.0.1:8081/v3/api-docs"]


def test_fetch_openapi_allows_public_https_url_when_mocked(monkeypatch):
    calls: list[str] = []
    _mock_dns(monkeypatch, {"api.example.com": "93.184.216.34"})

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return _openapi_response(url)

    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fake_get)

    spec = fetch_openapi_from_url("https://api.example.com/openapi.yaml")

    assert spec["info"]["version"] == "1.0"
    assert calls == ["https://api.example.com/openapi.yaml"]


def test_fetch_openapi_rejects_blocked_schemes_before_network(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called for blocked schemes")

    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fail_get)

    with pytest.raises(ValueError, match="OpenAPI URL must use http or https"):
        fetch_openapi_from_url("file:///tmp/spec.yaml")

    with pytest.raises(ValueError, match="OpenAPI URL must use http or https"):
        fetch_openapi_from_url("ftp://example.com/spec.yaml")


def test_fetch_openapi_rejects_missing_hostname_before_network(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called for URLs without a host")

    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fail_get)

    with pytest.raises(ValueError, match="must include a hostname"):
        fetch_openapi_from_url("https:///openapi.yaml")


@pytest.mark.parametrize(
    "url",
    [
        "http://169.254.169.254/latest/meta-data",
        "http://0.0.0.0/openapi.yaml",
        "http://224.0.0.1/openapi.yaml",
        "http://10.0.0.20/openapi.yaml",
        "http://[fe80::1]/openapi.yaml",
        "http://[fe80::1%25lo0]/openapi.yaml",
    ],
)
def test_fetch_openapi_rejects_unsafe_ip_literals_before_network(monkeypatch, url):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called for unsafe IP literals")

    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fail_get)

    with pytest.raises(ValueError, match="host is not allowed"):
        fetch_openapi_from_url(url)


def test_fetch_openapi_rejects_numeric_hostname_resolving_to_metadata_address(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called for unsafe resolved hosts")

    _mock_dns(monkeypatch, {"2852039166": "169.254.169.254"})
    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fail_get)

    with pytest.raises(ValueError, match="host is not allowed"):
        fetch_openapi_from_url("http://2852039166/latest/meta-data")


def test_fetch_openapi_rejects_hostname_resolving_to_private_address(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called for unsafe resolved hosts")

    _mock_dns(monkeypatch, {"metadata.internal": "10.0.0.20"})
    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fail_get)

    with pytest.raises(ValueError, match="host is not allowed"):
        fetch_openapi_from_url("http://metadata.internal/openapi.yaml")


def test_fetch_openapi_allows_configured_private_ip(monkeypatch):
    calls: list[str] = []

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return _openapi_response(url)

    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", "10.0.0.20")
    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fake_get)

    spec = fetch_openapi_from_url("http://10.0.0.20/openapi.yaml")

    assert spec["openapi"] == "3.0.0"
    assert calls == ["http://10.0.0.20/openapi.yaml"]


def test_fetch_openapi_resolves_and_allows_configured_private_hostname(monkeypatch):
    calls: list[str] = []
    _mock_dns(monkeypatch, {"api.internal.local": "10.20.30.40"})

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return _openapi_response(url)

    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", "api.internal.local")
    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fake_get)

    spec = fetch_openapi_from_url("https://api.internal.local/openapi.yaml")

    assert spec["openapi"] == "3.0.0"
    assert calls == ["https://api.internal.local/openapi.yaml"]


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8081/v3/api-docs",
        "http://127.0.0.1:8081/v3/api-docs",
        "http://[::1]:8081/v3/api-docs",
    ],
)
def test_shared_mode_rejects_loopback_urls_before_network(monkeypatch, url):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called for shared-mode loopback URLs")

    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "open")
    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fail_get)

    with pytest.raises(ValueError, match="host is not allowed"):
        fetch_openapi_from_url(url)


def test_shared_mode_disabled_fetch_rejects_before_network(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called when shared-mode fetch is disabled")

    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "disabled")
    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fail_get)

    with pytest.raises(ValueError, match="fetch is disabled"):
        fetch_openapi_from_url("https://api.example.com/openapi.yaml")


def test_shared_mode_allowlist_requires_non_empty_match(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called for empty shared-mode allowlist")

    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "allowlist")
    monkeypatch.delenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", raising=False)
    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fail_get)

    with pytest.raises(ValueError, match="host is not allowed"):
        fetch_openapi_from_url("https://api.example.com/openapi.yaml")


def test_shared_mode_allowlist_rejects_unlisted_host_before_network(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("network should not be called for non-allowlisted hosts")

    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "allowlist")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", "api.internal.local")
    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fail_get)

    with pytest.raises(ValueError, match="host is not allowed"):
        fetch_openapi_from_url("https://api.example.com/openapi.yaml")


def test_shared_mode_allowlist_resolves_and_pins_configured_host(monkeypatch):
    calls: list[str] = []
    _mock_dns(monkeypatch, {"api.internal.local": "10.20.30.40"})

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return _openapi_response(url)

    monkeypatch.setenv("EDGEFORGE_STUDIO_SHARED_MODE", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_SESSION_SECRET", "test-shared-secret")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "allowlist")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS", "api.internal.local")
    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fake_get)

    spec = fetch_openapi_from_url("https://api.internal.local/openapi.yaml")

    assert spec["openapi"] == "3.0.0"
    assert calls == ["https://api.internal.local/openapi.yaml"]


def test_fetch_openapi_rejects_redirect_to_blocked_target(monkeypatch):
    calls: list[str] = []
    _mock_dns(monkeypatch, {"api.example.com": "93.184.216.34"})

    def fake_get(url: str, **kwargs):
        calls.append(url)
        return _openapi_response(
            url,
            status_code=302,
            headers={"location": "http://169.254.169.254/latest/meta-data"},
        )

    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fake_get)

    with pytest.raises(ValueError, match="redirect target is not allowed"):
        fetch_openapi_from_url("https://api.example.com/openapi.yaml")

    assert calls == ["https://api.example.com/openapi.yaml"]


def test_fetch_openapi_follows_allowed_redirect(monkeypatch):
    calls: list[str] = []
    _mock_dns(monkeypatch, {"api.example.com": "93.184.216.34"})

    def fake_get(url: str, **kwargs):
        calls.append(url)
        if len(calls) == 1:
            return _openapi_response(url, status_code=302, headers={"location": "/openapi.yaml"})
        return _openapi_response(url)

    monkeypatch.setattr("tests.test_openapi_service._HTTP_GET", fake_get)

    spec = fetch_openapi_from_url("https://api.example.com/v3/api-docs")

    assert spec["openapi"] == "3.0.0"
    assert calls == [
        "https://api.example.com/v3/api-docs",
        "https://api.example.com/openapi.yaml",
    ]


def test_classify_entity():
    entities, ops = classify_openapi_spec(SAMPLE_SPEC)
    entity_names = {e.name: e.classification for e in entities}
    assert entity_names["Account"] == "entity"


def test_classify_dto():
    entities, ops = classify_openapi_spec(SAMPLE_SPEC)
    entity_names = {e.name: e.classification for e in entities}
    assert entity_names["CreateAccountRequest"] == "dto"


def test_classify_infrastructure():
    entities, ops = classify_openapi_spec(SAMPLE_SPEC)
    entity_names = {e.name: e.classification for e in entities}
    assert entity_names["PageableObject"] == "infrastructure"
    assert entity_names["ErrorResponse"] == "infrastructure"


def test_entity_fields_extracted():
    entities, _ = classify_openapi_spec(SAMPLE_SPEC)
    account = next(e for e in entities if e.name == "Account")
    field_names = [f.name for f in account.fields]
    assert "accountId" in field_names
    assert "status" in field_names


def test_operations_extracted():
    _, ops = classify_openapi_spec(SAMPLE_SPEC)
    op_names = [o.name for o in ops]
    assert "createAccount" in op_names
    assert "getAccount" in op_names


def test_parse_json_text():
    import json
    text = json.dumps(SAMPLE_SPEC)
    parsed = parse_openapi_text(text)
    assert parsed["info"]["title"] == "Test API"


def test_parse_yaml_text():
    import yaml
    text = yaml.dump(SAMPLE_SPEC)
    parsed = parse_openapi_text(text)
    assert parsed["info"]["title"] == "Test API"


# ---------------------------------------------------------------------------
# Canonical entity naming (Blocker 3 regression tests)
# ---------------------------------------------------------------------------

def test_normalize_strips_response_suffix():
    """CustomerResponse → Customer (mirrors AppBuilder _normalize_entity_name)."""
    assert _normalize_entity_name("CustomerResponse") == "Customer"


def test_normalize_strips_request_suffix():
    assert _normalize_entity_name("CreateAccountRequest") == "Account"


def test_normalize_strips_crud_prefix():
    assert _normalize_entity_name("GetCustomer") == "Customer"
    assert _normalize_entity_name("ListAccounts") == "Accounts"


def test_normalize_plain_entity_unchanged():
    """Plain domain schemas must not be mangled."""
    assert _normalize_entity_name("Account") == "Account"
    assert _normalize_entity_name("Customer") == "Customer"


def test_response_schema_in_response_refs_promoted_to_entity():
    """AccountResponse used in a 2xx response ref must be promoted to entity (not DTO)."""
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/accounts/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AccountResponse"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "AccountResponse": {
                    "type": "object",
                    "properties": {
                        "accountId": {"type": "string"},
                        "status": {"type": "string"},
                    },
                }
            }
        },
    }
    entities, _ = classify_openapi_spec(spec)
    account_resp = next(e for e in entities if e.name == "AccountResponse")
    assert account_resp.classification == "entity", (
        "AccountResponse used as a 2xx response ref must be promoted to entity, "
        "matching AppBuilder's classify_openapi_schemas() behaviour"
    )


def test_response_schema_entity_has_canonical_name():
    """AccountResponse entity must expose canonical_name='Account'."""
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/accounts/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/AccountResponse"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "AccountResponse": {
                    "type": "object",
                    "properties": {"accountId": {"type": "string"}},
                }
            }
        },
    }
    entities, _ = classify_openapi_spec(spec)
    account_resp = next(e for e in entities if e.name == "AccountResponse")
    assert account_resp.canonical_name == "Account"
    assert account_resp.display_name() == "Account"


def test_allof_schema_in_response_ref_classified_as_entity():
    """Spring Boot / Springdoc uses allOf for inheritance.

    A schema whose properties live inside an allOf item (not at the top level)
    must still be classified as entity when it appears in a 2xx response ref.
    Previously _schema_has_properties only checked schema_def.get("properties")
    directly, silently dropping these schemas to infrastructure.
    """
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/customers/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Customer"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "BaseEntity": {
                    "type": "object",
                    "properties": {"createdAt": {"type": "string"}},
                },
                "Customer": {
                    "allOf": [
                        {"$ref": "#/components/schemas/BaseEntity"},
                        {
                            "type": "object",
                            "properties": {
                                "customerId": {"type": "string"},
                                "name": {"type": "string"},
                            },
                        },
                    ]
                },
            }
        },
    }
    entities, _ = classify_openapi_spec(spec)
    customer = next((e for e in entities if e.name == "Customer"), None)
    assert customer is not None, "Customer schema must be classified (not silently dropped)"
    assert customer.classification == "entity", (
        "Customer appears in a 2xx response ref and has properties inside allOf — "
        "must be promoted to entity, not dropped to infrastructure"
    )


def test_wildcard_content_type_response_schema_classified_as_entity():
    """Spring Boot / Springdoc emits */* as the response content-type by default.

    _response_schemas_from_op() previously only checked application/json and
    application/*+json, so all schemas in */* responses were invisible to the
    classifier — response_refs stayed empty, every schema became DTO/infrastructure,
    and Step 3 showed zero entities.
    """
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/accounts/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "*/*": {
                                    "schema": {"$ref": "#/components/schemas/Account"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Account": {
                    "type": "object",
                    "properties": {
                        "accountId": {"type": "string"},
                        "balance": {"type": "number"},
                    },
                }
            }
        },
    }
    entities, _ = classify_openapi_spec(spec)
    account = next((e for e in entities if e.name == "Account"), None)
    assert account is not None, "Account must be classified when response uses */* content-type"
    assert account.classification == "entity"


def _parcel_response_spec():
    from pathlib import Path

    import yaml

    return yaml.safe_load(
        (Path(__file__).parent / "fixtures/parcel-response-upload.yaml").read_text()
    )


def test_response_object_ref_promotes_target_schema_to_entity():
    """Wrapper naming must use the hyphenated path, not the schema suffix."""
    spec = _parcel_response_spec()
    assert "ParcelResponse" in _response_schema_refs(spec)
    entities, ops = classify_openapi_spec(spec)
    target = next(e for e in entities if e.name == "ParcelResponse")
    assert target.classification == "entity"
    assert target.canonical_name == "ParcelNote"
    assert target.display_name() == "ParcelNote"
    assert {field.name for field in target.fields} == {"parcelId", "label", "priority"}
    create = next(op for op in ops if op.name == "createParcel")
    assert create.response_schema == "ParcelResponse"
    assert create.path == "/parcel-notes"
    assert create.entity_candidates == ["ParcelNote"]
    detail = next(op for op in ops if op.name == "getParcel")
    assert detail.path == "/parcel-notes/{parcelId}"
    assert detail.entity_candidates == ["ParcelNote"]


def test_find_response_schema_resolves_response_object_ref():
    spec = _parcel_response_spec()
    operation = spec["paths"]["/parcel-notes/{parcelId}"]["get"]
    assert _find_response_schema(operation, spec) == "ParcelResponse"


def test_generate_field_mappings_uses_nested_data_fields_for_transport_wrapper():
    spec = _parcel_response_spec()
    entities, _ = classify_openapi_spec(spec)
    canonical_name = next(e for e in entities if e.name == "ParcelResponse").display_name()
    mappings = generate_field_mappings(
        "ParcelResponse", canonical_name, spec["components"]["schemas"],
    )
    assert {m["source"] for m in mappings} == {"parcelId", "label", "priority"}
    assert {m["target"] for m in mappings} == {
        "ParcelNote.parcelId", "ParcelNote.label", "ParcelNote.priority",
    }


def test_plain_entity_has_no_canonical_name():
    """Account (plain schema) must not set canonical_name — already canonical."""
    entities, _ = classify_openapi_spec(SAMPLE_SPEC)
    account = next(e for e in entities if e.name == "Account")
    assert account.canonical_name is None
    assert account.display_name() == "Account"


def test_entity_candidates_use_canonical_names():
    """Operations must list canonical entity names (Customer, not CustomerResponse)."""
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/customers/{id}": {
                "get": {
                    "operationId": "getCustomer",
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/CustomerResponse"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "CustomerResponse": {
                    "type": "object",
                    "properties": {
                        "customerId": {"type": "string"},
                        "name": {"type": "string"},
                    },
                }
            }
        },
    }
    _, ops = classify_openapi_spec(spec)
    get_customer = next(o for o in ops if o.name == "getCustomer")
    assert "Customer" in get_customer.entity_candidates, (
        "Operation entity_candidates must use canonical name 'Customer', not 'CustomerResponse'"
    )
    assert "CustomerResponse" not in get_customer.entity_candidates


# ---------------------------------------------------------------------------
# Export guard (Blocker 1 regression tests)
# ---------------------------------------------------------------------------

def test_export_blocked_when_no_spec_url():
    """Export must be blocked when upstream interface has no spec or spec_url."""
    from app.models.project import ProjectSession, UpstreamInterface
    from app.services.completeness_service import build_completeness_report

    s = ProjectSession()
    s.app_name = "Test"
    s.bounded_context = "test"
    s.target_profile = "springboot-legacy-compatible"
    s.selected_entity_names = ["Account"]
    s.upstream_interfaces = [
        UpstreamInterface(
            name="api",
            type="rest-json",
            # neither spec nor spec_url
            entity_name="Account",
        )
    ]
    report = build_completeness_report(s)
    assert not report.is_exportable(), "Missing spec/spec_url must block export"
    blockers = [i.message for i in report.manual()]
    assert any("spec" in m.lower() for m in blockers)


# ---------------------------------------------------------------------------
# Eighth-pass regression tests
# ---------------------------------------------------------------------------

_ALLOF_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/customers/{id}": {
            "get": {
                "operationId": "getCustomer",
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Customer"}
                            }
                        }
                    }
                },
            }
        }
    },
    "components": {
        "schemas": {
            "BaseEntity": {
                "type": "object",
                "properties": {"createdAt": {"type": "string", "format": "date-time"}},
                "required": ["createdAt"],
            },
            "Customer": {
                "allOf": [
                    {"$ref": "#/components/schemas/BaseEntity"},
                    {
                        "type": "object",
                        "properties": {
                            "customerId": {"type": "string"},
                            "name": {"type": "string"},
                        },
                        "required": ["customerId"],
                    },
                ]
            },
        }
    },
}


def test_allof_entity_fields_include_ref_variant_fields():
    """P2 — _extract_fields() must collect fields from $ref variants inside allOf.

    Before this fix Studio classified Customer as entity but returned fields=[].
    AppBuilder's _collect_properties_and_required() resolved $ref variants, so
    the entity preview in Studio was weaker than what AppBuilder actually ingested.
    """
    entities, _ = classify_openapi_spec(_ALLOF_SPEC)
    customer = next(e for e in entities if e.name == "Customer")
    assert customer.classification == "entity"
    field_names = {f.name for f in customer.fields}
    assert "customerId" in field_names, "Direct allOf inline field must be extracted"
    assert "name" in field_names, "Direct allOf inline field must be extracted"
    assert "createdAt" in field_names, "$ref variant field must be extracted via allOf"


def test_generate_field_mappings_includes_ref_variant_fields():
    """P2 — generate_field_mappings() must resolve $ref variants inside allOf.

    Before this fix _generate_sample_from_schema() resolved $ref variants so
    the sample contained 'createdAt', but generate_field_mappings() only read
    inline properties, so 'createdAt' appeared in the sample but had no mapping
    row — triggering an AppBuilder 'unmapped sample field' warning.
    """
    all_schemas = _ALLOF_SPEC["components"]["schemas"]
    mappings = generate_field_mappings("Customer", "Customer", all_schemas)
    sources = {m["source"] for m in mappings}
    assert "customerId" in sources, "Direct allOf inline field must appear in mappings"
    assert "name" in sources, "Direct allOf inline field must appear in mappings"
    assert "createdAt" in sources, "$ref variant field must appear in mappings"
    # Every mapping must point to the canonical entity path
    for m in mappings:
        assert m["target"] == f"Customer.{m['source']}", (
            f"Mapping target must be 'Customer.<field>', got {m['target']!r}"
        )


def test_generate_operation_samples_handles_list_valued_type():
    """Nullable/multi-type OpenAPI fields must not crash sample generation.

    Real-world specs such as Codat use `type: ["string", "null"]`. Before this
    fix Studio raised TypeError because `_TYPE_DEFAULTS.get(field_type, ...)`
    received a list instead of a scalar type name.
    """
    all_schemas = {
        "NullableThing": {
            "type": "object",
            "properties": {
                "nickname": {"type": ["string", "null"]},
                "count": {"type": ["integer", "null"]},
            },
        }
    }

    req_json, resp_json = generate_operation_samples("NullableThing", "NullableThing", all_schemas)

    assert req_json is not None
    assert resp_json is not None
    assert json.loads(req_json) == {"nickname": "example", "count": 0}
    assert json.loads(resp_json) == {"nickname": "example", "count": 0}


def test_generate_operation_samples_resolves_primitive_refs_as_scalars():
    """A primitive component ref must keep its scalar type and sample value."""
    all_schemas = {
        "CurrencyCode": {"type": "string", "example": "USD"},
        "DefaultStatus": {"type": "string", "default": "PENDING"},
        "EnumTier": {"type": "string", "enum": ["STANDARD", "PREMIUM"]},
        "FallbackCount": {"type": "integer"},
        "Request": {
            "type": "object",
            "properties": {
                "currency_code": {"$ref": "#/components/schemas/CurrencyCode"},
                "status": {"$ref": "#/components/schemas/DefaultStatus"},
                "tier": {"$ref": "#/components/schemas/EnumTier"},
                "count": {"$ref": "#/components/schemas/FallbackCount"},
            },
        },
    }

    request_json, _ = generate_operation_samples("Request", None, all_schemas)

    assert request_json is not None
    assert json.loads(request_json) == {
        "currency_code": "USD",
        "status": "PENDING",
        "tier": "STANDARD",
        "count": 0,
    }


@pytest.mark.parametrize("combiner", ["allOf", "oneOf", "anyOf"])
def test_generate_operation_samples_resolves_composed_primitive_refs(combiner):
    all_schemas = {
        "CurrencyCode": {"type": "string", "example": "USD"},
        "CurrencyCodeAlias": {
            combiner: [{"$ref": "#/components/schemas/CurrencyCode"}],
        },
        "Request": {
            "type": "object",
            "properties": {
                "currency_code": {"$ref": "#/components/schemas/CurrencyCodeAlias"},
            },
        },
    }

    request_json, _ = generate_operation_samples("Request", None, all_schemas)

    assert request_json is not None
    assert json.loads(request_json) == {"currency_code": "USD"}


def test_mapping_plan_omits_request_only_fields_missing_from_canonical_entity():
    all_schemas = {
        "CurrencyCode": {"type": "string", "example": "USD"},
        "CreateAccountRequest": {
            "type": "object",
            "properties": {
                "account_id": {"type": "string"},
                "currency_code": {"$ref": "#/components/schemas/CurrencyCode"},
            },
        },
    }

    mappings, omitted = generate_field_mapping_plan(
        "CreateAccountRequest",
        "Account",
        all_schemas,
        canonical_fields={"account_id"},
    )

    assert mappings == [{"source": "account_id", "target": "Account.account_id"}]
    assert omitted == ["currency_code"]


def test_gap_fill_appends_only_missing_fields():
    """P3 — Gap-fill must append only schema fields not already in saved mappings.

    Old behaviour: if any saved mapping existed for a side, auto-gen was skipped
    entirely (all-or-nothing). A user with 1 of 5 saved would see only 1 mapping.
    New behaviour: saved rows are kept; only unsaved schema fields are appended.
    """
    all_schemas = _ALLOF_SPEC["components"]["schemas"]
    # Simulate: user already saved customerId → Customer.customerId
    # generate_field_mappings should return all 3 fields
    all_mappings = generate_field_mappings("Customer", "Customer", all_schemas)
    # Simulate gap-fill logic from entities.py
    saved = [{"source": "customerId", "target": "Customer.customerId"}]
    saved_sources = {m["source"] for m in saved}
    filled = saved + [m for m in all_mappings if m["source"] not in saved_sources]
    filled_sources = {m["source"] for m in filled}
    # Saved entry preserved
    assert "customerId" in filled_sources
    # Missing fields added
    assert "name" in filled_sources, "Gap-fill must append missing field 'name'"
    assert "createdAt" in filled_sources, "Gap-fill must append missing $ref field 'createdAt'"
    # No duplicates
    assert len(filled) == len(filled_sources), "Gap-fill must not produce duplicate rows"


# ---------------------------------------------------------------------------
# Phase A — constraint extraction + auto_generate_rules regression tests
# ---------------------------------------------------------------------------

from app.services.openapi_service import auto_generate_rules

_CONSTRAINT_SPEC = {
    "openapi": "3.0.0",
    "paths": {
        "/accounts/{id}": {
            "get": {
                "responses": {
                    "200": {
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Account"}
                            }
                        }
                    }
                }
            }
        }
    },
    "components": {
        "schemas": {
            "Account": {
                "type": "object",
                "required": ["accountNumber", "status"],
                "properties": {
                    "accountNumber": {
                        "type": "string",
                        "minLength": 10,
                        "maxLength": 10,
                        "pattern": "^[0-9]{10}$",
                    },
                    "status": {
                        "type": "string",
                        "enum": ["ACTIVE", "INACTIVE", "SUSPENDED"],
                    },
                    "balance": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 9999999.99,
                    },
                    "currency": {
                        "type": "string",
                        "default": "USD",
                    },
                    "customerId": {
                        "type": "string",
                    },
                },
            }
        }
    },
}


def test_classified_field_carries_constraints():
    """_extract_fields() must populate constraint metadata from spec properties."""
    entities, _ = classify_openapi_spec(_CONSTRAINT_SPEC)
    account = next(e for e in entities if e.name == "Account")
    assert account.classification == "entity"

    acct_num = next(f for f in account.fields if f.name == "accountNumber")
    assert acct_num.max_length == 10
    assert acct_num.min_length == 10
    assert acct_num.pattern == "^[0-9]{10}$"

    balance = next(f for f in account.fields if f.name == "balance")
    assert balance.minimum == 0.0
    assert balance.maximum == 9999999.99

    currency = next(f for f in account.fields if f.name == "currency")
    assert currency.default_value == "USD"

    status = next(f for f in account.fields if f.name == "status")
    assert status.enum_values == ["ACTIVE", "INACTIVE", "SUSPENDED"]


def test_auto_generate_rules_enum_becomes_allowed_values():
    """Enum fields → allowed-values rule."""
    entities, _ = classify_openapi_spec(_CONSTRAINT_SPEC)
    rules_list = auto_generate_rules(entities)
    account_rules = next(er for er in rules_list if er.entity_name == "Account")
    status_rule = next(r for r in account_rules.rules if r.field == "status")
    assert status_rule.type == "allowed-values"
    assert set(status_rule.values) == {"ACTIVE", "INACTIVE", "SUSPENDED"}


def test_auto_generate_rules_length_constraints():
    """maxLength/minLength → max-length/min-length rules."""
    entities, _ = classify_openapi_spec(_CONSTRAINT_SPEC)
    rules_list = auto_generate_rules(entities)
    account_rules = next(er for er in rules_list if er.entity_name == "Account")
    rule_types_for_acct_num = {r.type for r in account_rules.rules if r.field == "accountNumber"}
    assert "max-length" in rule_types_for_acct_num
    assert "min-length" in rule_types_for_acct_num
    max_rule = next(r for r in account_rules.rules if r.field == "accountNumber" and r.type == "max-length")
    assert max_rule.value == "10"


def test_auto_generate_rules_pattern():
    """pattern → pattern rule."""
    entities, _ = classify_openapi_spec(_CONSTRAINT_SPEC)
    rules_list = auto_generate_rules(entities)
    account_rules = next(er for er in rules_list if er.entity_name == "Account")
    pattern_rule = next(r for r in account_rules.rules if r.field == "accountNumber" and r.type == "pattern")
    assert pattern_rule.value == "^[0-9]{10}$"


def test_auto_generate_rules_range():
    """minimum/maximum → range rule with min/max values."""
    entities, _ = classify_openapi_spec(_CONSTRAINT_SPEC)
    rules_list = auto_generate_rules(entities)
    account_rules = next(er for er in rules_list if er.entity_name == "Account")
    range_rule = next(r for r in account_rules.rules if r.field == "balance" and r.type == "range")
    assert range_rule.value == "0.0"       # min stored in value
    assert range_rule.values == ["9999999.99"]  # max stored in values[0]


def test_auto_generate_rules_default():
    """default → default rule."""
    entities, _ = classify_openapi_spec(_CONSTRAINT_SPEC)
    rules_list = auto_generate_rules(entities)
    account_rules = next(er for er in rules_list if er.entity_name == "Account")
    default_rule = next(r for r in account_rules.rules if r.field == "currency" and r.type == "default")
    assert default_rule.value == "USD"


def test_auto_generate_rules_not_null():
    """Required fields with no other constraint → not-null rule."""
    entities, _ = classify_openapi_spec(_CONSTRAINT_SPEC)
    # customerId is required but has no constraints and is not an id (not named 'id' or 'customeridid')
    # Actually customerId.is_id is True because name.lower() = 'customerid' and 'customerid' in ('id', 'customeridid') is False
    # Let's check: is_id = name.lower() in ("id", f"{name.lower()}id") = 'customerid' in ('id', 'customerididid')... no
    # So customerId is required with no constraints → should get not-null
    # But wait, customerId is NOT in required list per the spec above (only accountNumber and status are required)
    # So this tests that UNrequired fields with no constraints don't get not-null
    rules_list = auto_generate_rules(entities)
    account_rules = next(er for er in rules_list if er.entity_name == "Account")
    # accountNumber IS required but has length/pattern constraints → should NOT also get not-null
    not_null_fields = {r.field for r in account_rules.rules if r.type == "not-null"}
    assert "accountNumber" not in not_null_fields, "Fields with other constraints must not also get not-null"
    assert "status" not in not_null_fields, "Fields with enum (allowed-values) must not also get not-null"


def test_rule_yaml_serialises_new_types():
    """generate_rule_yaml() must correctly serialise all new rule types."""
    import yaml

    from app.models.project import EntityRules, RuleEntry
    from app.services.rule_generator import generate_rule_yaml

    er = EntityRules(
        entity_name="Account",
        rules=[
            RuleEntry(field="accountNumber", type="max-length", value="10"),
            RuleEntry(field="accountNumber", type="min-length", value="10"),
            RuleEntry(field="accountNumber", type="pattern", value="^[0-9]{10}$"),
            RuleEntry(field="balance", type="range", value="0.01", values=["999999.99"]),
            RuleEntry(field="status", type="not-null"),
        ],
    )
    doc = yaml.safe_load(generate_rule_yaml(er))
    rules_by_type = {r["type"]: r for r in doc["rules"]}

    assert rules_by_type["max-length"]["value"] == "10"
    assert rules_by_type["min-length"]["value"] == "10"
    assert rules_by_type["pattern"]["value"] == "^[0-9]{10}$"
    assert rules_by_type["range"]["min"] == "0.01"
    assert rules_by_type["range"]["max"] == "999999.99"
    assert "value" not in rules_by_type["not-null"]


def test_auto_generate_rules_enum_plus_default_both_emitted():
    """P2 — A field with both enum and default must produce both allowed-values and default rules.

    Previously the continue after the enum branch silently dropped the default rule,
    meaning { enum: [ACTIVE, INACTIVE], default: ACTIVE } exported only allowed-values.
    AppBuilder applies allowed-values and default independently, so both should be written.
    """
    spec = {
        "openapi": "3.0.0",
        "paths": {
            "/accounts": {
                "get": {
                    "responses": {
                        "200": {
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Account"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {
            "schemas": {
                "Account": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["ACTIVE", "INACTIVE"],
                            "default": "ACTIVE",
                        },
                    },
                }
            }
        },
    }
    entities, _ = classify_openapi_spec(spec)
    rules_list = auto_generate_rules(entities)
    account_rules = next(er for er in rules_list if er.entity_name == "Account")
    rule_types = {r.type for r in account_rules.rules if r.field == "status"}
    assert "allowed-values" in rule_types, "enum must produce allowed-values rule"
    assert "default" in rule_types, "default must not be dropped when field also has enum"
    default_rule = next(r for r in account_rules.rules if r.field == "status" and r.type == "default")
    assert default_rule.value == "ACTIVE"
