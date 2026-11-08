"""Deterministic XML/XSD and SOAP/WSDL artifact inspection helpers."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from io import StringIO
from typing import Any

from app.services.edge_contracts import SOAP_WSDL_TYPE, XML_XSD_TYPE, clean_text

XSD_NS = "http://www.w3.org/2001/XMLSchema"
WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"
SOAP_BINDING_NAMESPACES = {
    "http://schemas.xmlsoap.org/wsdl/soap/",
    "http://schemas.xmlsoap.org/wsdl/soap12/",
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if tag.startswith("{") else tag


def _namespace(tag: str) -> str | None:
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return None


def _collect_namespaces(content: str) -> dict[str, str]:
    namespaces: dict[str, str] = {}
    try:
        for event, item in ET.iterparse(StringIO(content), events=("start-ns",)):
            if event == "start-ns":
                prefix, uri = item
                namespaces[prefix or ""] = uri
    except ET.ParseError:
        return {}
    return namespaces


def _has_forbidden_xml_declaration(text: str) -> bool:
    """Scan declarations once, ignoring XML regions where markup is text.

    This is intentionally a small lexical preflight, not another XML parser.
    Every search resumes after the prior region, keeping malformed inputs linear.
    ElementTree remains responsible for reporting malformed XML.
    """
    position = 0
    text_length = len(text)
    ignored_sections = (
        ("<!--", "-->"),
        ("<![CDATA[", "]]>"),
        ("<?", "?>"),
    )
    forbidden_names = ("DOCTYPE", "ENTITY")

    while position < text_length:
        marker = text.find("<", position)
        if marker < 0:
            return False

        skipped = False
        for opening, closing in ignored_sections:
            if not text.startswith(opening, marker):
                continue
            end = text.find(closing, marker + len(opening))
            if end < 0:
                # The XML parser will reject the unterminated region. Nothing
                # after it can be active markup, so declaration scanning is done.
                return False
            position = end + len(closing)
            skipped = True
            break
        if skipped:
            continue

        if text.startswith("<!", marker):
            name_start = marker + 2
            while name_start < text_length and text[name_start].isspace():
                name_start += 1
            for name in forbidden_names:
                name_end = name_start + len(name)
                if text[name_start:name_end].upper() != name:
                    continue
                if name_end == text_length or not (
                    text[name_end].isalnum() or text[name_end] == "_"
                ):
                    return True
        position = marker + 1

    return False


def _parse_xml(
    content: str | bytes,
    *,
    label: str,
) -> tuple[ET.Element | None, list[str]]:
    """Parse XML while refusing active DTD and entity declarations."""
    if isinstance(content, bytes):
        source: str | bytes = content
        # Strip XML-encoding NUL padding only for the declaration guard. The
        # original bytes still go to ElementTree so their XML declaration
        # controls decoding just as it does when the Engine parses the file.
        guarded = source.replace(b"\x00", b"").decode("latin-1")
        forbidden = _has_forbidden_xml_declaration(guarded)
    else:
        source = clean_text(content) or ""
        forbidden = _has_forbidden_xml_declaration(source)
    if not source:
        return None, [f"Paste {label} content before inspection. Reference-only contracts can still export if complete."]
    if forbidden:
        return None, [f"{label} inspection does not allow DTD or entity declarations."]
    try:
        return ET.fromstring(source), []
    except ET.ParseError as exc:
        return None, [f"Malformed {label}: {exc}"]


def _qname_parts(value: str | None) -> tuple[str | None, str | None]:
    text = clean_text(value)
    if not text:
        return None, None
    if ":" in text:
        prefix, name = text.split(":", 1)
        return prefix, name
    return None, text


def _prefixed(name: str, namespace_alias: str | None) -> str:
    return f"{namespace_alias}:{name}" if namespace_alias else name


def _xsd_direct_attributes(node: ET.Element) -> list[ET.Element]:
    return [
        child
        for child in list(node)
        if _namespace(child.tag) == XSD_NS and _local_name(child.tag) == "attribute"
    ]


def _xsd_direct_sequence_elements(node: ET.Element) -> list[ET.Element]:
    elements: list[ET.Element] = []
    for child in list(node):
        if _namespace(child.tag) == XSD_NS and _local_name(child.tag) == "sequence":
            elements.extend(
                grandchild
                for grandchild in list(child)
                if _namespace(grandchild.tag) == XSD_NS and _local_name(grandchild.tag) == "element"
            )
    return elements


def _xsd_has_inline_complex_type(node: ET.Element) -> bool:
    return any(
        _namespace(child.tag) == XSD_NS and _local_name(child.tag) == "complexType"
        for child in list(node)
    )


def _xsd_field_candidates(root: ET.Element, root_element_name: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Best-effort field/attribute candidates for user-assisted mapping rows."""
    complex_types = {
        node.attrib.get("name"): node
        for node in root.iter()
        if _namespace(node.tag) == XSD_NS
        and _local_name(node.tag) == "complexType"
        and node.attrib.get("name")
    }
    root_local = _qname_parts(root_element_name)[1] or root_element_name
    root_node = next(
        (
            node
            for node in root
            if _namespace(node.tag) == XSD_NS
            and _local_name(node.tag) == "element"
            and (_qname_parts(node.attrib.get("name") or node.attrib.get("ref"))[1] == root_local)
        ),
        None,
    )
    if root_node is None:
        return [], []

    _, type_name = _qname_parts(root_node.attrib.get("type"))
    complex_node = complex_types.get(type_name or "")
    if complex_node is None:
        complex_node = next(
            (
                child
                for child in list(root_node)
                if _namespace(child.tag) == XSD_NS and _local_name(child.tag) == "complexType"
            ),
            None,
        )
    if complex_node is None:
        return [], []

    fields: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for attr in _xsd_direct_attributes(complex_node):
        name = attr.attrib.get("name") or attr.attrib.get("ref")
        _, local = _qname_parts(name)
        if not local or local in seen:
            continue
        seen.add(local)
        fields.append(
            {
                "name": local,
                "kind": "attribute",
                "type": attr.attrib.get("type"),
                "required": attr.attrib.get("use") == "required",
            }
        )
    for element in _xsd_direct_sequence_elements(complex_node):
        name = element.attrib.get("name") or element.attrib.get("ref")
        _, local = _qname_parts(name)
        if not local or local in seen:
            continue
        _, element_type = _qname_parts(element.attrib.get("type"))
        if _xsd_has_inline_complex_type(element) or (element_type and element_type in complex_types):
            warnings.append(
                f"XML/XSD field '{local}' is nested or complex and was not offered for mapping seeding. "
                "Engine currently supports direct scalar root fields only."
            )
            continue
        seen.add(local)
        fields.append(
            {
                "name": local,
                "kind": "element",
                "type": element.attrib.get("type"),
                "required": element.attrib.get("minOccurs") != "0",
            }
        )
    return fields, warnings


def _namespace_alias(target_namespace: str | None, namespaces: dict[str, str]) -> str | None:
    if target_namespace:
        for prefix, uri in namespaces.items():
            if uri == target_namespace and prefix:
                return prefix
        tail = re.split(r"[/#:]", target_namespace.rstrip("/#"))[-1]
        alias = re.sub(r"[^A-Za-z0-9_]+", "", tail or "")
        if alias and not alias[0].isdigit():
            return alias[:12]
    return None


def inspect_xml_xsd(content: str) -> dict[str, Any]:
    root, errors = _parse_xml(content, label="XSD")
    if errors:
        return {"ok": False, "candidates": {}, "selected": {}, "warnings": [], "errors": errors}

    namespaces = _collect_namespaces(content)
    target_namespace = root.attrib.get("targetNamespace") if root is not None else None
    alias = _namespace_alias(target_namespace, namespaces)
    warnings: list[str] = []
    elements: list[dict[str, str | None]] = []

    if root is None:
        return {"ok": False, "candidates": {}, "selected": {}, "warnings": [], "errors": ["Unable to parse XSD."]}

    for node in root.iter():
        local = _local_name(node.tag)
        ns = _namespace(node.tag)
        if ns == XSD_NS and local in {"include", "import"}:
            ref = node.attrib.get("schemaLocation") or node.attrib.get("namespace") or "external schema"
            warnings.append(f"Unresolved XSD {local}: {ref}. Studio does not fetch external imports/includes during inspection.")
        if ns == XSD_NS and local in {"choice", "all", "any"}:
            warnings.append(f"Unsupported XSD construct detected: xs:{local}. Review mappings manually in a later slice.")
        if node.attrib.get("mixed") == "true":
            warnings.append("Mixed XML content detected. Studio does not derive canonical fields from mixed content yet.")

    complex_type_names = {
        node.attrib.get("name")
        for node in root.iter()
        if _namespace(node.tag) == XSD_NS and _local_name(node.tag) == "complexType" and node.attrib.get("name")
    }
    for node in root:
        if _namespace(node.tag) != XSD_NS or _local_name(node.tag) != "element":
            continue
        name = node.attrib.get("name") or node.attrib.get("ref")
        if not name:
            continue
        _, local_name = _qname_parts(name)
        type_prefix, type_name = _qname_parts(node.attrib.get("type"))
        if local_name and type_name and local_name == type_name and type_name in complex_type_names:
            warnings.append(f"Recursive-looking XSD element/type detected: {local_name}. Review manually before generation.")
        elements.append(
            {
                "name": name,
                "qualified_name": _prefixed(name, alias) if ":" not in name else name,
                "type": node.attrib.get("type"),
                "namespace": target_namespace,
                "namespace_alias": alias,
                "type_prefix": type_prefix,
            }
        )

    field_candidates: list[dict[str, Any]] = []
    if len(elements) == 1 and elements[0].get("name"):
        field_candidates, field_warnings = _xsd_field_candidates(root, str(elements[0]["name"]))
        warnings.extend(field_warnings)

    selected = {}
    if len(elements) == 1:
        selected = {
            "root_element": elements[0]["qualified_name"],
            "namespace": target_namespace,
            "namespace_alias": alias,
        }

    return {
        "ok": True,
        "candidates": {
            "target_namespace": target_namespace,
            "namespace_alias": alias,
            "root_elements": elements,
            "fields": field_candidates,
        },
        "selected": selected,
        "warnings": warnings,
        "errors": [],
    }


def _children(node: ET.Element, namespace: str | None, local_name: str) -> list[ET.Element]:
    return [
        child
        for child in list(node)
        if _local_name(child.tag) == local_name and (namespace is None or _namespace(child.tag) == namespace)
    ]


def _first_child(node: ET.Element, namespace: str | None, local_name: str) -> ET.Element | None:
    matches = _children(node, namespace, local_name)
    return matches[0] if matches else None


def inspect_soap_wsdl(content: str) -> dict[str, Any]:
    root, errors = _parse_xml(content, label="WSDL")
    if errors:
        return {"ok": False, "candidates": {}, "selected": {}, "warnings": [], "errors": errors}
    if root is None:
        return {"ok": False, "candidates": {}, "selected": {}, "warnings": [], "errors": ["Unable to parse WSDL."]}

    target_namespace = root.attrib.get("targetNamespace")
    warnings: list[str] = []

    for node in root.iter():
        if _namespace(node.tag) == WSDL_NS and _local_name(node.tag) in {"import", "include"}:
            ref = node.attrib.get("location") or node.attrib.get("namespace") or "external WSDL"
            warnings.append(f"Unresolved WSDL {_local_name(node.tag)}: {ref}. Studio does not fetch imports during inspection.")

    bindings_by_name: dict[str, dict[str, Any]] = {}
    operations: list[dict[str, Any]] = []
    for binding in _children(root, WSDL_NS, "binding"):
        binding_name = binding.attrib.get("name")
        soap_binding = None
        for child in list(binding):
            if _local_name(child.tag) == "binding" and _namespace(child.tag) in SOAP_BINDING_NAMESPACES:
                soap_binding = child
                break
        is_soap = soap_binding is not None
        style = soap_binding.attrib.get("style") if soap_binding is not None else None
        if not is_soap and binding_name:
            warnings.append(f"Binding '{binding_name}' is not a SOAP binding and will not be selected automatically.")
        if style == "rpc" and binding_name:
            warnings.append(f"Binding '{binding_name}' uses RPC style. RPC/encoded SOAP is not supported in this slice.")

        binding_ops: list[dict[str, Any]] = []
        for op in _children(binding, WSDL_NS, "operation"):
            op_name = op.attrib.get("name")
            soap_op = None
            for child in list(op):
                if _local_name(child.tag) == "operation" and _namespace(child.tag) in SOAP_BINDING_NAMESPACES:
                    soap_op = child
                    break
            soap_action = soap_op.attrib.get("soapAction") if soap_op is not None else None
            op_style = soap_op.attrib.get("style") if soap_op is not None else style
            for body in op.iter():
                if _local_name(body.tag) == "body" and _namespace(body.tag) in SOAP_BINDING_NAMESPACES:
                    if body.attrib.get("use") == "encoded":
                        warnings.append(f"Operation '{op_name}' uses encoded SOAP body. Encoded SOAP is not supported.")
            item = {
                "name": op_name,
                "binding": binding_name,
                "soap_action": soap_action,
                "style": op_style,
                "is_soap": soap_op is not None,
            }
            binding_ops.append(item)
            operations.append(item)

        if binding_name:
            bindings_by_name[binding_name] = {
                "name": binding_name,
                "type": binding.attrib.get("type"),
                "is_soap": is_soap,
                "style": style,
                "operations": binding_ops,
            }

    services: list[dict[str, Any]] = []
    ports: list[dict[str, Any]] = []
    for service in _children(root, WSDL_NS, "service"):
        service_name = service.attrib.get("name")
        service_ports = []
        for port in _children(service, WSDL_NS, "port"):
            _, binding_name = _qname_parts(port.attrib.get("binding"))
            port_item = {
                "name": port.attrib.get("name"),
                "service": service_name,
                "binding": binding_name,
                "is_soap": bool(binding_name and bindings_by_name.get(binding_name, {}).get("is_soap")),
            }
            ports.append(port_item)
            service_ports.append(port_item)
        services.append({"name": service_name, "ports": service_ports})

    soap_ports = [port for port in ports if port.get("is_soap")]
    soap_bindings = [binding for binding in bindings_by_name.values() if binding.get("is_soap")]
    if len(services) > 1:
        warnings.append("Multiple WSDL services detected. Select the intended service explicitly.")
    if len(soap_ports) > 1:
        warnings.append("Multiple SOAP ports detected. Select the intended port explicitly.")
    if not soap_bindings:
        warnings.append("No SOAP binding was found in this WSDL.")

    selected: dict[str, Any] = {}
    if len(services) == 1 and len(soap_ports) == 1:
        selected["service"] = services[0]["name"]
        selected["port"] = soap_ports[0]["name"]
        selected["binding"] = soap_ports[0]["binding"]
        binding_ops = bindings_by_name.get(str(soap_ports[0]["binding"]), {}).get("operations", [])
        if len(binding_ops) == 1:
            selected["operation"] = binding_ops[0]["name"]

    return {
        "ok": True,
        "candidates": {
            "target_namespace": target_namespace,
            "services": services,
            "ports": ports,
            "bindings": list(bindings_by_name.values()),
            "operations": operations,
        },
        "selected": selected,
        "warnings": warnings,
        "errors": [],
    }


def inspect_edge_contract_artifact(contract_type: str, content: str) -> dict[str, Any]:
    if contract_type == XML_XSD_TYPE:
        return inspect_xml_xsd(content)
    if contract_type == SOAP_WSDL_TYPE:
        return inspect_soap_wsdl(content)
    return {
        "ok": False,
        "candidates": {},
        "selected": {},
        "warnings": [],
        "errors": ["Artifact inspection is only available for XML/XSD and SOAP/WSDL contracts."],
    }
