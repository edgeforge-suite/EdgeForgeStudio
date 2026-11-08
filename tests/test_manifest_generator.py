"""Tests for manifest generation."""

import copy

import pytest
import yaml

from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DownstreamInterface,
    FieldMapping,
    IdentityRoleDecision,
    OperationMapping,
    OperationSample,
    ProjectSession,
    SoapCanonicalInvocationConfig,
    SoapCanonicalOperationConfig,
    SoapRequestMapping,
    SoapResponseMapping,
    SoapReturnMapping,
    UpstreamInterface,
)
from app.services import manifest_generator
from app.services.manifest_contract import STUDIO_MANIFEST_SCHEMA_VERSION
from app.services.manifest_generator import build_manifest_dict, generate_manifest_yaml


def _base_session() -> ProjectSession:
    s = ProjectSession()
    s.app_name = "Test App"
    s.bounded_context = "test"
    s.target_profile = "springboot-legacy-compatible"
    return s


def test_required_fields():
    s = _base_session()
    d = build_manifest_dict(s)
    assert d["app_name"] == "Test App"
    assert d["bounded_context"] == "test"
    assert d["target_profile"] == "springboot-legacy-compatible"


def test_manifest_v2_contract_fields():
    """Exported manifest includes the active Engine version and archetype."""
    s = _base_session()
    d = build_manifest_dict(s)
    assert STUDIO_MANIFEST_SCHEMA_VERSION == "2.0"
    assert d["schema_version"] == STUDIO_MANIFEST_SCHEMA_VERSION
    assert d["app_archetype"] == "crud"


def test_manifest_v2_field_order():
    """schema_version and app_archetype must appear before optional interface fields in YAML."""
    s = _base_session()
    yml = generate_manifest_yaml(s)
    lines = yml.splitlines()
    keys = [ln.split(":")[0].strip() for ln in lines if ":" in ln and not ln.startswith(" ")]
    schema_idx = keys.index("schema_version")
    archetype_idx = keys.index("app_archetype")
    # Both must be present and schema_version before app_archetype
    assert schema_idx < archetype_idx


@pytest.mark.parametrize("archetype", ["crud", "passthrough-router", "kafka-integration"])
def test_every_archetype_emits_manifest_v2(archetype):
    session = _base_session()
    session.app_archetype = archetype

    assert build_manifest_dict(session)["schema_version"] == "2.0"


def test_manifest_v2_cut_changes_only_schema_version(monkeypatch):
    session = _base_session()
    session.upstream_interfaces = [
        UpstreamInterface(name="accounts", type="rest-json", spec="contracts/accounts.yaml")
    ]
    current = build_manifest_dict(session)
    current_keys = list(current)

    monkeypatch.setattr(manifest_generator, "STUDIO_MANIFEST_SCHEMA_VERSION", "1.0")
    previous = build_manifest_dict(copy.deepcopy(session))

    assert list(previous) == current_keys
    assert previous["schema_version"] == "1.0"
    assert current["schema_version"] == "2.0"
    previous.pop("schema_version")
    current.pop("schema_version")
    assert current == previous


def test_openapi_fetch_security_settings_do_not_change_manifest(monkeypatch):
    session = _base_session()
    session.upstream_interfaces = [
        UpstreamInterface(
            name="accounts",
            type="rest-json",
            spec_url="https://api.example.com/openapi.json",
        )
    ]
    expected = generate_manifest_yaml(session)

    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MODE", "allowlist")
    monkeypatch.setenv(
        "EDGEFORGE_STUDIO_OPENAPI_FETCH_ALLOWED_HOSTS",
        "api.example.com",
    )
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_MAX_BYTES", "1024")
    monkeypatch.setenv("EDGEFORGE_STUDIO_OPENAPI_FETCH_TIMEOUT_SECONDS", "3")

    assert generate_manifest_yaml(session) == expected


def test_no_optional_keys_when_empty():
    s = _base_session()
    d = build_manifest_dict(s)
    assert "upstream_interfaces" not in d
    assert "downstream_interfaces" not in d
    assert "data_handoffs" not in d
    assert "rules" not in d
    assert "identity_overrides" not in d
    assert "identity_roles" not in d


def test_identity_overrides_export_persistence_id_only_for_crud():
    s = _base_session()
    s.classified_entities = [
        ClassifiedEntity(
            name="Transaction",
            fields=[
                ClassifiedField(name="transactionRowId", type="string"),
                ClassifiedField(name="customerId", type="string"),
            ],
        )
    ]
    s.selected_entity_names = ["Transaction"]
    s.identity_role_decisions = [
        IdentityRoleDecision(entity="Transaction", field="transactionRowId", role="persistence_id"),
        IdentityRoleDecision(entity="Transaction", field="customerId", role="parent_reference"),
    ]

    d = build_manifest_dict(s)

    assert d["identity_overrides"] == [
        {"entity": "Transaction", "persistence_id": "transactionRowId"}
    ]
    assert "customerId" not in str(d["identity_overrides"])
    assert d["identity_roles"] == [
        {
            "entity": "Transaction",
            "field": "customerId",
            "role": "parent_reference",
            "mode": "metadata_only",
        }
    ]
    assert "persistence_id" not in str(d["identity_roles"])


def test_non_persistence_identity_roles_export_metadata_only_for_crud():
    s = _base_session()
    s.classified_entities = [
        ClassifiedEntity(
            name="Account",
            fields=[
                ClassifiedField(name="accountNumber", type="string"),
                ClassifiedField(name="externalAccountRef", type="string"),
            ],
        )
    ]
    s.selected_entity_names = ["Account"]
    s.identity_role_decisions = [
        IdentityRoleDecision(
            entity="Account",
            field="externalAccountRef",
            role="external_reference",
            provenance="knowledge-assist",
        ),
        IdentityRoleDecision(entity="Account", field="accountNumber", role="business_key"),
    ]

    d = build_manifest_dict(s)

    assert "identity_overrides" not in d
    assert d["identity_roles"] == [
        {
            "entity": "Account",
            "field": "accountNumber",
            "role": "business_key",
            "mode": "metadata_only",
        },
        {
            "entity": "Account",
            "field": "externalAccountRef",
            "role": "external_reference",
            "mode": "metadata_only",
        },
    ]
    assert "policy" not in str(d["identity_roles"])
    assert "active" not in str(d["identity_roles"])


def test_identity_roles_omit_empty_persistence_and_non_crud_flows():
    s = _base_session()
    s.classified_entities = [
        ClassifiedEntity(name="Account", fields=[ClassifiedField(name="accountNumber", type="string")])
    ]
    s.selected_entity_names = ["Account"]

    s.identity_role_decisions = [
        IdentityRoleDecision(entity="Account", field="accountNumber", role="persistence_id")
    ]
    d = build_manifest_dict(s)
    assert d["identity_overrides"] == [
        {"entity": "Account", "persistence_id": "accountNumber"}
    ]
    assert "identity_roles" not in d

    s.app_archetype = "passthrough-router"
    s.identity_role_decisions = [
        IdentityRoleDecision(entity="Account", field="accountNumber", role="business_key")
    ]
    d = build_manifest_dict(s)
    assert "identity_overrides" not in d
    assert "identity_roles" not in d

    s.app_archetype = "kafka-integration"
    d = build_manifest_dict(s)
    assert "identity_overrides" not in d
    assert "identity_roles" not in d


def test_upstream_with_spec_url():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="crm-api",
            system="CRM",
            type="rest-json",
            spec_url="https://example.com/swagger.json",
            entity_name="Account",
            operations=[
                OperationSample(
                    name="createAccount",
                    request_sample_path="upstream/req.json",
                    response_sample_path="upstream/resp.json",
                )
            ],
        )
    ]
    d = build_manifest_dict(s)
    assert "upstream_interfaces" in d
    iface = d["upstream_interfaces"][0]
    assert iface["name"] == "crm-api"
    assert iface["spec_url"] == "https://example.com/swagger.json"
    assert "spec" not in iface   # must not have both
    assert iface["operations"][0]["name"] == "createAccount"


def test_upstream_with_local_spec():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="loan-api",
            type="rest-json",
            spec="contracts/loans.yaml",
            entity_name="Loan",
        )
    ]
    d = build_manifest_dict(s)
    iface = d["upstream_interfaces"][0]
    assert iface["spec"] == "contracts/loans.yaml"
    assert "spec_url" not in iface


def test_rules_are_file_paths():
    """rules must be a list of file paths, not inline objects."""
    from app.models.project import EntityRules, RuleEntry
    s = _base_session()
    s.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[RuleEntry(field="status", type="default", value="PENDING")],
            file_path="rules/account-business-rules.yaml",
        )
    ]
    d = build_manifest_dict(s)
    assert "rules" in d
    assert isinstance(d["rules"], list)
    assert d["rules"][0] == "rules/account-business-rules.yaml"
    # Must NOT be a dict/object
    assert not isinstance(d["rules"][0], dict)


def test_empty_rule_entries_are_omitted_from_manifest():
    """Only entities with actual rule entries should appear in manifest rules[]."""
    from app.models.project import EntityRules, RuleEntry

    s = _base_session()
    s.entity_rules = [
        EntityRules(
            entity_name="Account",
            rules=[RuleEntry(field="status", type="default", value="PENDING")],
            file_path="rules/account-business-rules.yaml",
        ),
        EntityRules(
            entity_name="TransactionHistory",
            rules=[],
            file_path="rules/transactionhistory-business-rules.yaml",
        ),
    ]

    d = build_manifest_dict(s)
    assert d["rules"] == ["rules/account-business-rules.yaml"]


def test_yaml_is_valid():
    s = _base_session()
    yml = generate_manifest_yaml(s)
    parsed = yaml.safe_load(yml)
    assert parsed["app_name"] == "Test App"


def test_mutual_exclusivity_spec_and_spec_url():
    """Must have spec or spec_url, not both."""
    s = _base_session()
    iface = UpstreamInterface(
        name="test",
        type="rest-json",
        spec="local.yaml",
        entity_name="X",
    )
    d = build_manifest_dict(s)
    # With local spec — no spec_url key
    s.upstream_interfaces = [iface]
    d = build_manifest_dict(s)
    iface_d = d["upstream_interfaces"][0]
    assert "spec" in iface_d
    assert "spec_url" not in iface_d


def test_edge_contract_manifest_exports_file_xml_and_soap_interfaces():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-fixed-in",
            type="file-fixed-width",
            spec="upstream/account-fixed-layout.yaml",
            entity_name="Account",
            field_mappings=[FieldMapping(source="account_id", target="Account.accountId")],
            mapping_path="upstream/account-fixed-mapping.yaml",
        ),
        UpstreamInterface(
            name="account-xml-in",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="acct:Account",
            namespace="urn:accounts:v1",
            namespace_alias="acct",
        ),
        UpstreamInterface(
            name="account-soap-in",
            type="soap-wsdl",
            wsdl_path="contracts/account.wsdl",
            service="AccountService",
            port="AccountPort",
            binding="AccountBinding",
        ),
    ]
    s.downstream_interfaces = [
        DownstreamInterface(
            name="account-csv-out",
            type="file-csv",
            spec="downstream/account-csv-layout.yaml",
            mapping_path="downstream/account-csv-mapping.yaml",
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
            samples=["downstream/account-csv-sample.csv"],
        ),
        DownstreamInterface(
            name="account-xml-out",
            type="xml-xsd",
            xsd_path="contracts/account-out.xsd",
            root_element="acct:AccountOut",
        ),
        DownstreamInterface(
            name="account-soap-out",
            type="soap-wsdl",
            wsdl_path="contracts/account-client.wsdl",
        ),
    ]

    d = build_manifest_dict(s)

    assert d["upstream_interfaces"] == [
        {
            "name": "account-fixed-in",
            "type": "file-fixed-width",
            "spec": "upstream/account-fixed-layout.yaml",
            "mapping": "upstream/account-fixed-mapping.yaml",
        },
        {
            "name": "account-xml-in",
            "type": "xml-xsd",
            "xsd_path": "contracts/account.xsd",
            "root_element": "acct:Account",
            "namespace": "urn:accounts:v1",
            "namespace_alias": "acct",
        },
        {
            "name": "account-soap-in",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/account.wsdl",
            "service": "AccountService",
            "port": "AccountPort",
            "binding": "AccountBinding",
        },
    ]
    assert d["downstream_interfaces"] == [
        {
            "name": "account-csv-out",
            "type": "file-csv",
            "spec": "downstream/account-csv-layout.yaml",
            "mapping": "downstream/account-csv-mapping.yaml",
            "samples": ["downstream/account-csv-sample.csv"],
        },
        {
            "name": "account-xml-out",
            "type": "xml-xsd",
            "xsd_path": "contracts/account-out.xsd",
            "root_element": "acct:AccountOut",
        },
        {
            "name": "account-soap-out",
            "type": "soap-wsdl",
            "wsdl_path": "contracts/account-client.wsdl",
        },
    ]
    assert all("direction" not in item for item in d["upstream_interfaces"])
    assert all("direction" not in item for item in d["downstream_interfaces"])


def test_upstream_file_contract_with_reviewed_mappings_exports_mapping_reference():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="account_id", target="accountId"),
            ],
        )
    ]

    d = build_manifest_dict(s)

    assert d["upstream_interfaces"] == [
        {
            "name": "account-csv-in",
            "type": "file-csv",
            "spec": "upstream/account-csv-layout.yaml",
            "mapping": "upstream/account-csv-in-mapping.yaml",
        }
    ]


def test_upstream_file_contract_without_entity_does_not_emit_incomplete_mapping_reference():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            field_mappings=[
                FieldMapping(source="account_id", target="accountId"),
            ],
        )
    ]

    d = build_manifest_dict(s)

    assert d["upstream_interfaces"] == [
        {
            "name": "account-csv-in",
            "type": "file-csv",
            "spec": "upstream/account-csv-layout.yaml",
        }
    ]


def test_upstream_file_contract_ignores_stale_mapping_path_without_current_mappings():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            entity_name="Account",
            mapping_path="upstream/stale-account-csv-in-mapping.yaml",
        )
    ]

    d = build_manifest_dict(s)

    assert d["upstream_interfaces"] == [
        {
            "name": "account-csv-in",
            "type": "file-csv",
            "spec": "upstream/account-csv-layout.yaml",
        }
    ]


def test_xml_contracts_with_reviewed_mappings_export_mapping_references():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml-in",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="AccountMessage",
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="accountId", target="accountId"),
            ],
        )
    ]
    s.downstream_interfaces = [
        DownstreamInterface(
            name="account-xml-out",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="AccountMessage",
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="Account.accountId", target="accountId"),
            ],
        )
    ]

    d = build_manifest_dict(s)

    assert d["upstream_interfaces"] == [
        {
            "name": "account-xml-in",
            "type": "xml-xsd",
            "xsd_path": "contracts/account.xsd",
            "root_element": "AccountMessage",
            "mapping": "upstream/account-xml-in-mapping.yaml",
        }
    ]
    assert d["downstream_interfaces"] == [
        {
            "name": "account-xml-out",
            "type": "xml-xsd",
            "xsd_path": "contracts/account.xsd",
            "root_element": "AccountMessage",
            "mapping": "downstream/account-xml-out-mapping.yaml",
        }
    ]
    assert "data_handoffs" not in d


def test_xml_contracts_do_not_emit_incomplete_mapping_references():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml-in",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="AccountMessage",
            mapping_path="upstream/stale-account-xml-in-mapping.yaml",
        ),
        UpstreamInterface(
            name="account-xml-no-entity",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="AccountMessage",
            mapping_path="upstream/stale-account-xml-no-entity-mapping.yaml",
            field_mappings=[FieldMapping(source="accountId", target="Account.accountId")],
        ),
    ]
    s.downstream_interfaces = [
        DownstreamInterface(
            name="account-xml-out",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="AccountMessage",
            mapping_path="downstream/stale-account-xml-out-mapping.yaml",
        )
    ]

    d = build_manifest_dict(s)

    assert all("mapping" not in entry for entry in d["upstream_interfaces"])
    assert all("mapping" not in entry for entry in d["downstream_interfaces"])


def test_xml_and_unselected_soap_edge_contracts_do_not_emit_stale_mapping_reference():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="xml-in",
            type="xml-xsd",
            xsd_path="contracts/input.xsd",
            root_element="Input",
            mapping_path="upstream/stale-xml-mapping.yaml",
        ),
        UpstreamInterface(
            name="soap-in",
            type="soap-wsdl",
            wsdl_path="contracts/service.wsdl",
            mapping_path="mappings/stale-soap-operation-mapping.yaml",
        ),
    ]

    d = build_manifest_dict(s)

    assert [entry["type"] for entry in d["upstream_interfaces"]] == ["xml-xsd", "soap-wsdl"]
    assert all("mapping" not in entry for entry in d["upstream_interfaces"])


def test_edge_contract_manifest_omits_incomplete_xml_and_soap_entries():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(name="missing-root", type="xml-xsd", xsd_path="contracts/missing-root.xsd"),
        UpstreamInterface(name="missing-wsdl", type="soap-wsdl"),
    ]

    d = build_manifest_dict(s)

    assert "upstream_interfaces" not in d


def test_edge_contract_manifest_omits_incomplete_file_csv_entry():
    s = _base_session()
    s.downstream_interfaces = [
        DownstreamInterface(name="csv-out", type="file-csv")
    ]

    d = build_manifest_dict(s)

    assert "downstream_interfaces" not in d


def test_soap_manifest_type_matches_engine_contract():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="soap",
            type="soap-wsdl",
            wsdl_path="contracts/service.wsdl",
        )
    ]

    d = build_manifest_dict(s)

    assert d["upstream_interfaces"][0]["type"] == "soap-wsdl"
    assert "soap" != d["upstream_interfaces"][0]["type"]


def test_upstream_soap_selected_operation_exports_mapping_without_sampleless_operations():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="customer-soap-service",
            type="soap-wsdl",
            wsdl_path="contracts/customer-service.wsdl",
            service="CustomerService",
            port="CustomerServicePort",
            binding="CustomerServiceBinding",
            selected_operation_name="getCustomer",
        )
    ]

    d = build_manifest_dict(s)

    iface = d["upstream_interfaces"][0]
    assert "operations" not in iface
    assert iface["mapping"] == "mappings/customer-soap-service-operation-mapping.yaml"


def test_upstream_soap_canonical_mapping_requires_verified_persistence_model_to_export():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="customer-soap-service",
            type="soap-wsdl",
            wsdl_path="contracts/customer-service.wsdl",
            selected_operation_name="getCustomer",
            soap_operation_mode="canonical",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Customer",
                lookup_field="customerNumber",
                request_path="/GetCustomerRequest/customerNumber",
                response_mappings=[
                    SoapResponseMapping(
                        source="Customer.customerNumber",
                        target_path="/GetCustomerResponse/customerNumber",
                    )
                ],
            ),
        )
    ]
    s.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[ClassifiedField(name="customerNumber", type="string")],
        )
    ]

    d = build_manifest_dict(s)

    assert "upstream_interfaces" not in d


def test_downstream_soap_selected_operation_exports_mapping_without_operations_wrapper():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="unselected-soap",
            type="soap-wsdl",
            wsdl_path="contracts/unselected.wsdl",
            mapping_path="mappings/stale-operation-mapping.yaml",
        )
    ]
    s.downstream_interfaces = [
        DownstreamInterface(
            name="customer-soap-client",
            type="soap-wsdl",
            wsdl_path="contracts/customer-client.wsdl",
            selected_operation_name="getCustomer",
        )
    ]

    d = build_manifest_dict(s)

    assert "operations" not in d["upstream_interfaces"][0]
    assert "mapping" not in d["upstream_interfaces"][0]
    assert "operations" not in d["downstream_interfaces"][0]
    assert d["downstream_interfaces"][0]["mapping"] == "mappings/customer-soap-client-operation-mapping.yaml"
    assert "data_handoffs" not in d


def test_downstream_soap_canonical_invoke_by_id_exports_mapping_only():
    s = _base_session()
    s.classified_entities = [
        ClassifiedEntity(
            name="Customer",
            fields=[
                ClassifiedField(name="customerId", type="string", is_id=True),
                ClassifiedField(name="status", type="string"),
            ],
        )
    ]
    s.identity_role_decisions = [
        IdentityRoleDecision(entity="Customer", field="customerId", role="persistence_id")
    ]
    s.downstream_interfaces = [
        DownstreamInterface(
            name="customer-soap-client",
            type="soap-wsdl",
            wsdl_path="contracts/customer-client.wsdl",
            service="CustomerSyncService",
            port="CustomerSyncServicePort",
            binding="CustomerSyncServiceBinding",
            selected_operation_name="syncCustomer",
            soap_operation_mode="canonical",
            soap_canonical_invocation=SoapCanonicalInvocationConfig(
                entity="Customer",
                lookup_field="customerId",
                request_mappings=[
                    SoapRequestMapping(source="Customer.customerId", target_path="/SyncCustomerRequest/customerId"),
                ],
                response_mappings=[
                    SoapReturnMapping(source_path="/SyncCustomerResponse/resultCode", target="resultCode"),
                ],
            ),
        )
    ]

    d = build_manifest_dict(s)

    iface = d["downstream_interfaces"][0]
    assert iface["type"] == "soap-wsdl"
    assert iface["mapping"] == "mappings/customer-soap-client-operation-mapping.yaml"
    assert "operations" not in iface
    assert "data_handoffs" not in d


def test_xml_and_soap_manifest_entries_do_not_emit_spec_url():
    s = _base_session()
    s.upstream_interfaces = [
        UpstreamInterface(
            name="xml",
            type="xml-xsd",
            spec_url="https://example.com/schema.xsd",
            xsd_path="contracts/schema.xsd",
            root_element="Root",
        ),
        UpstreamInterface(
            name="soap",
            type="soap-wsdl",
            spec_url="https://example.com/service.wsdl",
            wsdl_path="contracts/service.wsdl",
        ),
    ]

    d = build_manifest_dict(s)

    assert [entry["type"] for entry in d["upstream_interfaces"]] == ["xml-xsd", "soap-wsdl"]
    assert all("spec_url" not in entry for entry in d["upstream_interfaces"])


# ---------------------------------------------------------------------------
# P1 + P2 upstream mapping shape regression tests
# ---------------------------------------------------------------------------

def test_upstream_mapping_uses_operation_name():
    """Upstream mapping YAML must use the operation name, not the interface name.

    AppBuilder's build_upstream_mapping_artifacts() validates that each
    mapping operation name matches a declared manifest operation.  Using the
    interface name as the operation name causes 'Mapping declares unknown
    operation <ifaceName>' errors.
    """
    from app.services.mapping_generator import generate_upstream_mapping

    iface = UpstreamInterface(
        name="customer-api",
        type="rest-json",
        spec_url="https://example.com/api.json",
        entity_name="Customer",
        operations=[
            OperationSample(name="getCustomer"),
            OperationSample(name="createCustomer"),
        ],
        operation_mappings=[
            OperationMapping(
                name="getCustomer",   # must be the operation name
                request_mappings=[FieldMapping(source="customerId", target="Customer.customerId")],
                response_mappings=[],
            ),
        ],
    )
    yaml_text = generate_upstream_mapping(iface)
    import yaml as _yaml
    doc = _yaml.safe_load(yaml_text)

    assert "operations" in doc
    op_names = [op["name"] for op in doc["operations"]]
    assert "getCustomer" in op_names, (
        "Mapping operation name must be the operation name ('getCustomer'), "
        "not the interface name ('customer-api')"
    )
    assert "customer-api" not in op_names


def test_upstream_mapping_direction():
    """Upstream mapping: source = API field name, target = Entity.fieldName.

    AppBuilder's _split_canonical_path() expects target to contain 'Entity.field'.
    If the source/target are swapped the translator fails at metadata resolution.
    """
    import yaml as _yaml

    from app.services.mapping_generator import generate_upstream_mapping

    iface = UpstreamInterface(
        name="customer-api",
        type="rest-json",
        spec_url="https://example.com/api.json",
        entity_name="Customer",
        operations=[OperationSample(name="getCustomer")],
        operation_mappings=[
            OperationMapping(
                name="getCustomer",
                request_mappings=[
                    # source = API field name, target = canonical path
                    FieldMapping(source="cust_id", target="Customer.customerId"),
                    FieldMapping(source="cust_name", target="Customer.name"),
                ],
                response_mappings=[],
            )
        ],
    )
    doc = _yaml.safe_load(generate_upstream_mapping(iface))
    op = doc["operations"][0]
    mapping = op["request_mappings"][0]

    # source must NOT contain a dot (it's an API field name)
    assert "." not in mapping["source"], (
        f"Upstream mapping source should be a plain API field name, got: {mapping['source']}"
    )
    # target must contain Entity.field dot notation
    assert "." in mapping["target"], (
        f"Upstream mapping target must be Entity.field canonical path, got: {mapping['target']}"
    )
    assert mapping["target"].startswith("Customer."), (
        f"Target must start with entity name 'Customer.', got: {mapping['target']}"
    )


# ---------------------------------------------------------------------------
# P3 canonical deduplication regression test
# ---------------------------------------------------------------------------

def test_canonical_dedup_in_mapping_produces_single_entity():
    """Two schemas normalising to the same canonical name must produce one entry.

    If 'CustomerResponse' and 'GetCustomerResponse' both map to 'Customer',
    the upstream mapping YAML should reference entity 'Customer' once.
    """
    import yaml as _yaml

    from app.services.mapping_generator import generate_upstream_mapping

    iface = UpstreamInterface(
        name="customer-api",
        type="rest-json",
        spec_url="https://example.com/api.json",
        entity_name="Customer",   # already deduplicated canonical name
        operations=[
            OperationSample(name="getCustomer"),
            OperationSample(name="listCustomers"),
        ],
        operation_mappings=[
            OperationMapping(
                name="getCustomer",
                request_mappings=[FieldMapping(source="id", target="Customer.customerId")],
                response_mappings=[],
            ),
            OperationMapping(
                name="listCustomers",
                request_mappings=[FieldMapping(source="id", target="Customer.customerId")],
                response_mappings=[],
            ),
        ],
    )
    doc = _yaml.safe_load(generate_upstream_mapping(iface))
    assert doc["entity"] == "Customer"
    op_names = {op["name"] for op in doc["operations"]}
    assert "getCustomer" in op_names
    assert "listCustomers" in op_names
    # Both operations must be under the SAME entity block — not duplicated
    assert len(doc["operations"]) == 2
