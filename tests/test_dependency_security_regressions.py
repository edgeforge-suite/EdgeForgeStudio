"""Bounded checks of the corrected libraries, not new Studio auth behavior."""
from __future__ import annotations

import dns.name
import pytest
from authlib.jose import JsonWebSignature
from fastmcp import FastMCP
from fastmcp.exceptions import NotFoundError
from fastmcp.server.auth import restrict_tag
from fastmcp.server.transforms.tool_transform import ToolTransform
from fastmcp.tools.base import Tool
from fastmcp.tools.tool_transform import ToolTransformConfig
from opentelemetry.trace import TraceState


@pytest.mark.asyncio
async def test_transformed_tool_is_authorized_before_direct_execution() -> None:
    executions = []

    def synthetic_tool() -> str:
        executions.append("called")
        return "synthetic allowed result"

    server = FastMCP("synthetic-transform-authorization")
    server.add_tool(Tool.from_function(
        synthetic_tool, name="tagged_tool", tags={"public"},
        auth=restrict_tag("admin", scopes=["admin"]),
    ))
    allowed = await server.call_tool("tagged_tool")
    assert allowed.content[0].text == "synthetic allowed result"
    assert executions == ["called"]

    server.add_transform(ToolTransform({
        "tagged_tool": ToolTransformConfig(tags={"admin"}),
    }))
    assert await server.list_tools() == []
    with pytest.raises(NotFoundError, match="Unknown tool"):
        await server.call_tool("tagged_tool")
    assert executions == ["called"]


def test_tracestate_preserves_valid_members() -> None:
    assert list(TraceState.from_header(["vendor=value,other=item"]).items()) == [
        ("vendor", "value"), ("other", "item"),
    ]


@pytest.mark.parametrize("whitespace", [" ", "\t"])
def test_tracestate_discards_oversized_adversarial_headers(whitespace: str) -> None:
    header = "a=b" + whitespace * 8192 + "x"
    assert list(TraceState.from_header([header]).items()) == []


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
def test_authlib_rejects_empty_hmac_keys_without_rejecting_valid_keys(algorithm: str) -> None:
    jws = JsonWebSignature(algorithms=[algorithm])
    payload = b'{"sub":"synthetic-regression"}'
    secret = b"synthetic-secret-" + b"x" * 64
    token = jws.serialize_compact({"alg": algorithm}, payload, secret)
    assert jws.deserialize_compact(token, secret)["payload"] == payload

    for empty_key in (b"", "", {"kty": "oct", "k": ""}):
        with pytest.raises(ValueError, match="must not be empty"):
            jws.serialize_compact({"alg": algorithm}, payload, empty_key)
        with pytest.raises(ValueError, match="must not be empty"):
            jws.deserialize_compact(token, empty_key)


def test_dns_wire_parser_bounds_pointer_chains_and_preserves_shallow_names() -> None:
    def chain(hops: int) -> tuple[bytes, int]:
        wire = bytearray(b"\x00")
        previous = 0
        for _ in range(hops):
            offset = len(wire)
            wire.extend((0xC000 | previous).to_bytes(2, "big"))
            previous = offset
        return bytes(wire), previous

    name, consumed = dns.name.from_wire(*chain(4))
    assert name == dns.name.root
    assert consumed == 2
    with pytest.raises(dns.name.PointerChainTooLong):
        dns.name.from_wire(*chain(32))


def test_joserfc_rejects_oversized_input_before_allocating_segments() -> None:
    from joserfc import jws
    from joserfc.errors import BadSignatureError, ExceededSizeError
    from joserfc.jwk import OctKey

    class SplitForbidden(bytes):
        def split(self, *args, **kwargs):
            raise AssertionError("oversized input split before rejection")

    registry = jws.JWSRegistry(algorithms=["HS256"])
    registry.max_header_length = 8
    registry.max_payload_length = 8
    registry.max_signature_length = 8
    with pytest.raises(ExceededSizeError):
        jws.deserialize_compact(
            SplitForbidden(b"e30." + b"x" * 32 + b".x"), None, registry=registry,
        )

    key = OctKey.import_key(b"synthetic-content-regression-material")
    token = jws.serialize_compact({"alg": "HS256"}, b"bounded control", key)
    assert jws.deserialize_compact(token, key).payload == b"bounded control"
    with pytest.raises(BadSignatureError):
        jws.deserialize_compact(token, OctKey.import_key(b"different-synthetic-control-material"))
