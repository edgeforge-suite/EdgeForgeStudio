"""Tests for mapping YAML generation (all three directions)."""

import yaml

from app.models.project import (
    DataHandoff,
    DownstreamInterface,
    FieldMapping,
    LayoutField,
    OperationMapping,
    SoapCanonicalInvocationConfig,
    SoapCanonicalOperationConfig,
    SoapRequestMapping,
    SoapResponseMapping,
    SoapReturnMapping,
    UpstreamInterface,
)
from app.services.mapping_generator import (
    generate_downstream_layout,
    generate_downstream_mapping,
    generate_downstream_soap_operation_mapping,
    generate_downstream_xml_mapping,
    generate_handoff_mapping,
    generate_soap_operation_mapping,
    generate_upstream_file_mapping,
    generate_upstream_mapping,
    generate_upstream_xml_mapping,
)


def test_upstream_mapping_shape():
    """Upstream mapping must have interface, entity, operations with request/response_mappings."""
    iface = UpstreamInterface(
        name="crm-account-api",
        type="rest-json",
        spec_url="https://example.com/swagger.json",
        entity_name="Account",
        operation_mappings=[
            OperationMapping(
                name="createAccount",
                request_mappings=[
                    FieldMapping(source="customerId", target="Account.customerId"),
                    FieldMapping(source="accountType", target="Account.accountType"),
                ],
                response_mappings=[
                    FieldMapping(source="accountId", target="Account.accountId"),
                    FieldMapping(source="status", target="Account.status"),
                ],
            )
        ],
    )
    yml = generate_upstream_mapping(iface)
    doc = yaml.safe_load(yml)

    assert doc["interface"] == "crm-account-api"
    assert doc["entity"] == "Account"
    ops = doc["operations"]
    assert len(ops) == 1
    op = ops[0]
    assert op["name"] == "createAccount"
    assert {"source": "customerId", "target": "Account.customerId"} in op["request_mappings"]
    assert {"source": "accountId", "target": "Account.accountId"} in op["response_mappings"]


def test_upstream_file_mapping_shape_and_plain_target_qualification():
    """Inbound file mappings use Engine's file field -> canonical field shape."""
    iface = UpstreamInterface(
        name="account-csv-in",
        type="file-csv",
        entity_name="Account",
        field_mappings=[
            FieldMapping(source="account_id", target="accountId"),
            FieldMapping(source="status", target="Account.status"),
        ],
    )

    yml = generate_upstream_file_mapping(iface)
    doc = yaml.safe_load(yml)

    assert doc == {
        "entity": "Account",
        "direction": "inbound",
        "field_mappings": [
            {"source": "account_id", "target": "Account.accountId"},
            {"source": "status", "target": "Account.status"},
        ],
    }
    assert "interface" not in doc
    assert "operations" not in doc


def test_upstream_xml_mapping_shape_and_plain_target_qualification():
    """Inbound XML mappings use Engine's XML field -> canonical field shape."""
    iface = UpstreamInterface(
        name="account-xml-in",
        type="xml-xsd",
        entity_name="Account",
        field_mappings=[
            FieldMapping(source="accountId", target="accountId"),
            FieldMapping(source="sourceSystem", target="Account.sourceSystem"),
        ],
    )

    yml = generate_upstream_xml_mapping(iface)
    doc = yaml.safe_load(yml)

    assert doc == {
        "entity": "Account",
        "direction": "inbound",
        "field_mappings": [
            {"source": "accountId", "target": "Account.accountId"},
            {"source": "sourceSystem", "target": "Account.sourceSystem"},
        ],
    }
    assert "interface" not in doc
    assert "operations" not in doc


def test_soap_adapter_operation_mapping_includes_mode_and_handler():
    iface = UpstreamInterface(
        name="customer-soap-service",
        type="soap-wsdl",
        selected_operation_name="getCustomer",
        soap_handler_method="handleLookupCustomer",
    )

    doc = yaml.safe_load(generate_soap_operation_mapping(iface))

    assert doc == {
        "operation_mappings": [
            {
                "operation": "getCustomer",
                "mode": "adapter_only",
                "handler_method": "handleLookupCustomer",
            }
        ]
    }


def test_soap_canonical_read_by_id_operation_mapping_shape():
    iface = UpstreamInterface(
        name="customer-soap-service",
        type="soap-wsdl",
        selected_operation_name="getCustomer",
        soap_operation_mode="canonical",
        soap_handler_method="handleGetCustomer",
        soap_canonical_operation=SoapCanonicalOperationConfig(
            entity="Customer",
            lookup_field="customerId",
            request_path="/GetCustomerRequest/customerId",
            response_mappings=[
                SoapResponseMapping(source="Customer.customerId", target_path="/GetCustomerResponse/customerId"),
                SoapResponseMapping(source="Customer.status", target_path="/GetCustomerResponse/status"),
            ],
            not_found_fault="customerFault",
            not_found_message="Customer not found",
        ),
    )

    doc = yaml.safe_load(generate_soap_operation_mapping(iface))

    assert doc == {
        "operation_mappings": [
            {
                "operation": "getCustomer",
                "mode": "canonical",
                "canonical_operation": {
                    "kind": "read_by_id",
                    "entity": "Customer",
                    "lookup": {
                        "request_path": "/GetCustomerRequest/customerId",
                        "field": "customerId",
                    },
                    "response_mappings": [
                        {
                            "source": "Customer.customerId",
                            "target_path": "/GetCustomerResponse/customerId",
                        },
                        {
                            "source": "Customer.status",
                            "target_path": "/GetCustomerResponse/status",
                        },
                    ],
                    "not_found_fault": {
                        "fault": "customerFault",
                        "message": "Customer not found",
                    },
                },
            }
        ]
    }
    assert "handler_method" not in doc["operation_mappings"][0]


def test_downstream_mapping_shape():
    """Downstream mapping must use interface + entity + field_mappings (no operations)."""
    iface = DownstreamInterface(
        name="eod-handoff-file",
        type="file-fixed-width",
        entity_name="Account",
        field_mappings=[
            FieldMapping(source="Account.accountId", target="account_id"),
            FieldMapping(source="Account.status", target="status"),
        ],
    )
    yml = generate_downstream_mapping(iface)
    doc = yaml.safe_load(yml)

    assert doc["interface"] == "eod-handoff-file"
    assert doc["entity"] == "Account"
    assert "field_mappings" in doc
    assert {"source": "Account.accountId", "target": "account_id"} in doc["field_mappings"]
    # Must not have 'table' key
    assert "table" not in doc


def test_downstream_xml_mapping_shape():
    """Outbound XML mappings use Engine's canonical field -> XML field shape."""
    iface = DownstreamInterface(
        name="account-xml-out",
        type="xml-xsd",
        entity_name="Account",
        field_mappings=[
            FieldMapping(source="Account.accountId", target="accountId"),
            FieldMapping(source="Account.sourceSystem", target="sourceSystem"),
        ],
    )
    yml = generate_downstream_xml_mapping(iface)
    doc = yaml.safe_load(yml)

    assert doc == {
        "entity": "Account",
        "direction": "outbound",
        "field_mappings": [
            {"source": "Account.accountId", "target": "accountId"},
            {"source": "Account.sourceSystem", "target": "sourceSystem"},
        ],
    }
    assert "interface" not in doc
    assert "table" not in doc


def test_downstream_soap_adapter_operation_mapping_shape():
    iface = DownstreamInterface(
        name="customer-soap-client",
        type="soap-wsdl",
        selected_operation_name="syncCustomer",
    )

    doc = yaml.safe_load(generate_downstream_soap_operation_mapping(iface))

    assert doc == {
        "operation_mappings": [
            {
                "operation": "syncCustomer",
                "mode": "adapter_only",
            }
        ]
    }


def test_downstream_soap_canonical_invoke_by_id_operation_mapping_shape():
    iface = DownstreamInterface(
        name="customer-soap-client",
        type="soap-wsdl",
        selected_operation_name="syncCustomer",
        soap_operation_mode="canonical",
        soap_canonical_invocation=SoapCanonicalInvocationConfig(
            entity="Customer",
            lookup_field="customerId",
            request_field="id",
            request_mappings=[
                SoapRequestMapping(source="Customer.customerId", target_path="/SyncCustomerRequest/customerId"),
                SoapRequestMapping(source="Customer.status", target_path="/SyncCustomerRequest/status"),
            ],
            response_mode="return_only",
            response_mappings=[
                SoapReturnMapping(source_path="/SyncCustomerResponse/resultCode", target="resultCode"),
                SoapReturnMapping(source_path="/SyncCustomerResponse/message", target="message"),
            ],
        ),
    )

    doc = yaml.safe_load(generate_downstream_soap_operation_mapping(iface))

    assert doc == {
        "operation_mappings": [
            {
                "operation": "syncCustomer",
                "mode": "canonical",
                "canonical_operation": {
                    "kind": "invoke_by_id",
                    "entity": "Customer",
                    "lookup": {
                        "request_field": "id",
                        "field": "customerId",
                    },
                    "request_mappings": [
                        {
                            "source": "Customer.customerId",
                            "target_path": "/SyncCustomerRequest/customerId",
                        },
                        {
                            "source": "Customer.status",
                            "target_path": "/SyncCustomerRequest/status",
                        },
                    ],
                    "response": {
                        "mode": "return_only",
                        "response_mappings": [
                            {
                                "source_path": "/SyncCustomerResponse/resultCode",
                                "target": "resultCode",
                            },
                            {
                                "source_path": "/SyncCustomerResponse/message",
                                "target": "message",
                            },
                        ],
                    },
                },
            }
        ]
    }


def test_handoff_mapping_shape():
    """Data handoff mapping must use table + entity + field_mappings (no interface key)."""
    handoff = DataHandoff(
        name="account-staging-table",
        type="staging-table",
        entity_name="Account",
        table_name="acct_staging_tbl",
        field_mappings=[
            FieldMapping(source="Account.accountId", target="acct_id"),
            FieldMapping(source="Account.customerId", target="cust_ref"),
        ],
    )
    yml = generate_handoff_mapping(handoff)
    doc = yaml.safe_load(yml)

    assert doc["table"] == "acct_staging_tbl"
    assert doc["entity"] == "Account"
    assert "field_mappings" in doc
    assert {"source": "Account.accountId", "target": "acct_id"} in doc["field_mappings"]
    # Must not have 'interface' key
    assert "interface" not in doc


def test_downstream_layout_shape():
    iface = DownstreamInterface(
        name="eod-handoff-file",
        type="file-fixed-width",
        layout_fields=[
            LayoutField(name="account_id", start=1, length=12),
            LayoutField(name="status", start=13, length=10),
        ],
    )
    yml = generate_downstream_layout(iface)
    doc = yaml.safe_load(yml)

    assert doc["name"] == "eod-handoff-file"
    assert doc["format"] == "fixed-width"
    assert "fields" not in doc
    fields = doc["record_types"]["data"]["fields"]
    assert fields[0] == {"name": "account_id", "position": 1, "length": 12}
    assert fields[1] == {"name": "status", "position": 13, "length": 10}
