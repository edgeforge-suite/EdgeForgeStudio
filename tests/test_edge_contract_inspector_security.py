"""XML/XSD and SOAP/WSDL content-inspection security acceptance tests.

Covers three properties of `app/services/edge_contract_inspector.py`:

1. The DOCTYPE/ENTITY guard shared by `inspect_xml_xsd` and
   `inspect_soap_wsdl` (via `_parse_xml`) categorically blocks XXE
   (external-entity file-read/SSRF) and billion-laughs-style internal
   entity expansion, because entities can only be declared inside a
   DOCTYPE - there is no separate code path to test for "billion laughs",
   the same regex closes both.
2. `xs:include`/`xs:import` `schemaLocation` and `wsdl:import` `location`
   values are only ever interpolated into a warning string - Studio never
   opens or fetches them, so path-traversal/absolute-path/file-uri/SSRF
   values passed there are inert (not applicable as "path traversal" in
   the traditional sense, since these endpoints take pasted content, not
   file paths).
3. No depth/size bound exists anywhere in this module today. These tests
   probe (rather than assume) what actually happens on deeply nested or
   very large well-formed documents.

This is a test-only PR: no production code is changed here. Any gap this
suite reveals is documented in the PR description as a candidate follow-up
[FIX] PR rather than patched inline.
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.edge_contract_inspector import (
    inspect_edge_contract_artifact,
    inspect_soap_wsdl,
    inspect_xml_xsd,
)
from app.services.edge_contracts import SOAP_WSDL_TYPE, XML_XSD_TYPE

client = TestClient(app)

_BOUNDED_RESULT_SECONDS = 5


# ---------------------------------------------------------------------------
# 1. XXE / DTD guard
# ---------------------------------------------------------------------------

XXE_PAYLOADS = {
    "classic_external_entity_file_read": (
        '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'
    ),
    "external_entity_ssrf": (
        '<!DOCTYPE foo [<!ENTITY xxe SYSTEM "http://169.254.169.254/latest/meta-data/">]>'
        "<foo>&xxe;</foo>"
    ),
    "billion_laughs_internal_entities": (
        "<!DOCTYPE lolz [\n"
        ' <!ENTITY lol "lol">\n'
        ' <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">\n'
        ' <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">\n'
        "]>\n<lolz>&lol3;</lolz>"
    ),
    "doctype_only_external_dtd_no_inline_entity": (
        '<!DOCTYPE foo SYSTEM "http://evil.example/ext.dtd"><foo>bar</foo>'
    ),
    "lowercase_doctype_is_still_blocked": (
        '<!doctype foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><foo>&xxe;</foo>'
    ),
    "whitespace_after_bang_before_entity": '<!  ENTITY xxe "test"><foo>bar</foo>',
    "whitespace_after_bang_before_doctype": "<!   DOCTYPE foo><foo>bar</foo>",
}


@pytest.mark.parametrize("payload", XXE_PAYLOADS.values(), ids=list(XXE_PAYLOADS))
def test_inspect_xml_xsd_rejects_dtd_and_entity_payloads(payload):
    # Completing at all (fast, no hang/crash) is itself part of the proof.
    result = inspect_xml_xsd(payload)

    assert result["ok"] is False
    assert result["errors"] == ["XSD inspection does not allow DTD or entity declarations."]
    assert result["candidates"] == {}
    assert result["selected"] == {}
    assert result["warnings"] == []


@pytest.mark.parametrize("payload", XXE_PAYLOADS.values(), ids=list(XXE_PAYLOADS))
def test_inspect_soap_wsdl_rejects_dtd_and_entity_payloads(payload):
    result = inspect_soap_wsdl(payload)

    assert result["ok"] is False
    assert result["errors"] == ["WSDL inspection does not allow DTD or entity declarations."]
    assert result["candidates"] == {}
    assert result["selected"] == {}
    assert result["warnings"] == []


def test_inspect_edge_contract_artifact_dispatches_xml_xsd_and_rejects_xxe():
    result = inspect_edge_contract_artifact(
        XML_XSD_TYPE, XXE_PAYLOADS["classic_external_entity_file_read"]
    )

    assert result["ok"] is False
    assert result["errors"] == ["XSD inspection does not allow DTD or entity declarations."]


def test_inspect_edge_contract_artifact_dispatches_soap_wsdl_and_rejects_xxe():
    result = inspect_edge_contract_artifact(
        SOAP_WSDL_TYPE, XXE_PAYLOADS["classic_external_entity_file_read"]
    )

    assert result["ok"] is False
    assert result["errors"] == ["WSDL inspection does not allow DTD or entity declarations."]


# ---------------------------------------------------------------------------
# HTTP layer - the pasted-content inspect routes must reject XXE the same
# way the service functions do, end to end, for both directions/types.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "direction,contract_type,label_word",
    [
        ("upstream", "xml-xsd", "XSD"),
        ("upstream", "soap-wsdl", "WSDL"),
        ("downstream", "xml-xsd", "XSD"),
        ("downstream", "soap-wsdl", "WSDL"),
    ],
)
def test_edge_contract_inspect_route_rejects_xxe_payload(direction, contract_type, label_word):
    response = client.post(
        f"/{direction}/edge-contract/inspect",
        json={
            "direction": direction,
            "type": contract_type,
            "content": XXE_PAYLOADS["classic_external_entity_file_read"],
        },
    )

    assert response.status_code == 400
    body = response.json()
    assert body["ok"] is False
    assert body["errors"] == [f"{label_word} inspection does not allow DTD or entity declarations."]


@pytest.mark.parametrize("direction", ["upstream", "downstream"])
def test_edge_contract_inspect_route_bounds_unterminated_comment_markers(direction):
    """Malformed marker scans must stay linear on the public synchronous route."""
    content = "<!--" * 20_000  # 80 KB, with no closing marker anywhere.

    start = time.monotonic()
    response = client.post(
        f"/{direction}/edge-contract/inspect",
        json={
            "direction": direction,
            "type": "xml-xsd",
            "content": content,
        },
    )
    elapsed = time.monotonic() - start

    assert elapsed < 2, (
        f"{direction} malformed-marker inspection took {elapsed:.2f}s; expected a linear bound"
    )
    assert response.status_code == 400
    assert response.json()["ok"] is False


# ---------------------------------------------------------------------------
# 2. "Path traversal" reframed: these endpoints take pasted content, not file
# paths. The only place path-like values appear is inside xs:include/
# xs:import schemaLocation and wsdl:import location - both are only ever
# interpolated into a warning string, never opened or fetched. A plain unit
# test passing cleanly and instantly (no missing-file error, no network
# hang) is itself the proof of inertness; no mocking of open()/socket is
# needed.
# ---------------------------------------------------------------------------

REFERENCE_VALUES = {
    "relative_path_traversal": "../../../../etc/passwd",
    "absolute_path": "/etc/passwd",
    "file_uri": "file:///etc/passwd",
    "ssrf_internal_url": "http://169.254.169.254/latest/meta-data/",
}


@pytest.mark.parametrize("ref", REFERENCE_VALUES.values(), ids=list(REFERENCE_VALUES))
def test_inspect_xml_xsd_treats_schema_location_references_as_inert(ref):
    xsd = f"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="urn:test:v1">
  <xs:include schemaLocation="{ref}"/>
  <xs:element name="Thing" type="xs:string"/>
</xs:schema>"""

    result = inspect_xml_xsd(xsd)

    assert result["ok"] is True
    assert result["errors"] == []
    assert any(ref in warning for warning in result["warnings"])
    assert any(
        "Studio does not fetch external imports/includes during inspection" in warning
        for warning in result["warnings"]
    )


@pytest.mark.parametrize("ref", REFERENCE_VALUES.values(), ids=list(REFERENCE_VALUES))
def test_inspect_soap_wsdl_treats_import_location_references_as_inert(ref):
    wsdl = f"""<?xml version="1.0"?>
<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/" targetNamespace="urn:test:v1">
  <wsdl:import namespace="urn:other:v1" location="{ref}"/>
</wsdl:definitions>"""

    result = inspect_soap_wsdl(wsdl)

    assert result["ok"] is True
    assert result["errors"] == []
    assert any(ref in warning for warning in result["warnings"])
    assert any(
        "Studio does not fetch imports during inspection" in warning for warning in result["warnings"]
    )


# ---------------------------------------------------------------------------
# 3. Depth/size - no explicit bound exists anywhere in
# edge_contract_inspector.py today. Verified against the real code (not
# assumed): both ET.fromstring and Element.iter() are backed here by the
# C-accelerated `_elementtree` module (confirmed: `ET.Element is
# _elementtree.Element`), which walks/builds the tree iteratively rather
# than via Python-level recursion, so deep nesting does not raise
# RecursionError even far beyond sys.getrecursionlimit(). No other function
# in this module recurses over the parsed tree either -
# `_xsd_field_candidates` only ever looks one level deep at a node's direct
# children. Empirically today this produces a clean, bounded, fast SUCCESS
# (ok=True) - but that specific outcome is an emergent property of the C
# accelerator, not a deliberate guarantee, and the PR description flags the
# missing explicit cap as a defense-in-depth follow-up candidate.
#
# These tests therefore assert the invariant we actually want - bounded,
# fast, well-formed completion (no crash, no hang, no exception) - WITHOUT
# requiring `ok is True`/`errors == []` specifically. If a future PR adds an
# explicit depth/size cap that deliberately rejects these exact payloads with
# a clean `ok: False` + error, that is the desired outcome of that follow-up
# and must not break this suite; only a crash, a hang, or a malformed result
# shape should fail these tests.
# ---------------------------------------------------------------------------


def _assert_bounded_deterministic_result(result: dict) -> None:
    """Assert a clean, well-formed, self-consistent result - either outcome is fine.

    Deliberately does NOT assert which of ok=True/ok=False the inspector
    produced: today's no-cap behavior returns ok=True for large/deep-but-
    well-formed input, but a future explicit depth/size cap should be free to
    return a clean ok=False + error for these same adversarial payloads
    without breaking this suite (see the section comment above).
    """
    assert isinstance(result, dict)
    assert isinstance(result.get("ok"), bool)
    assert isinstance(result.get("errors"), list)
    # Self-consistency: ok must exactly correlate with an empty errors list,
    # whichever of the two outcomes actually occurred.
    assert result["ok"] == (result["errors"] == [])


def test_inspect_xml_xsd_handles_deeply_nested_document_without_recursion_error():
    depth = 5000
    nested = "<a>" * depth + "leaf" + "</a>" * depth

    start = time.monotonic()
    result = inspect_xml_xsd(nested)
    elapsed = time.monotonic() - start

    assert elapsed < _BOUNDED_RESULT_SECONDS, (
        f"deeply nested XSD inspection took {elapsed:.2f}s, expected a bounded result"
    )
    _assert_bounded_deterministic_result(result)


def test_inspect_soap_wsdl_handles_deeply_nested_document_without_recursion_error():
    depth = 5000
    nested = (
        '<wsdl:definitions xmlns:wsdl="http://schemas.xmlsoap.org/wsdl/">'
        + "<a>" * depth
        + "leaf"
        + "</a>" * depth
        + "</wsdl:definitions>"
    )

    start = time.monotonic()
    result = inspect_soap_wsdl(nested)
    elapsed = time.monotonic() - start

    assert elapsed < _BOUNDED_RESULT_SECONDS, (
        f"deeply nested WSDL inspection took {elapsed:.2f}s, expected a bounded result"
    )
    _assert_bounded_deterministic_result(result)


def test_inspect_xml_xsd_handles_large_flat_document_without_hanging():
    count = 20000
    flat = "<root>" + "".join(f"<item id='{i}'>v{i}</item>" for i in range(count)) + "</root>"

    start = time.monotonic()
    result = inspect_xml_xsd(flat)
    elapsed = time.monotonic() - start

    assert elapsed < _BOUNDED_RESULT_SECONDS, (
        f"large flat XSD inspection took {elapsed:.2f}s, expected a bounded result"
    )
    _assert_bounded_deterministic_result(result)


def test_inspect_xml_xsd_handles_very_long_text_value_without_hanging():
    content = "<root><item>" + ("x" * 1_000_000) + "</item></root>"

    start = time.monotonic()
    result = inspect_xml_xsd(content)
    elapsed = time.monotonic() - start

    assert elapsed < _BOUNDED_RESULT_SECONDS, (
        f"very long text value inspection took {elapsed:.2f}s, expected a bounded result"
    )
    _assert_bounded_deterministic_result(result)
