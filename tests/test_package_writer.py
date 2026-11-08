"""Tests for package export — file tree and path validation."""

import tempfile
from pathlib import Path

import pytest
import yaml

from app.models.project import (
    ClassifiedEntity,
    ClassifiedField,
    DataHandoff,
    DownstreamInterface,
    EntityRules,
    FieldMapping,
    IdentityRoleDecision,
    KafkaConfig,
    KafkaRouteModel,
    KafkaRouterTargetTransform,
    KafkaRouterTransformRow,
    KafkaRouteTransform,
    KafkaTopicPair,
    LayoutField,
    OperationMapping,
    OperationSample,
    ProjectSession,
    RuleEntry,
    SoapCanonicalInvocationConfig,
    SoapCanonicalOperationConfig,
    SoapRequestMapping,
    SoapResponseMapping,
    SoapReturnMapping,
    UpstreamInterface,
)
from app.services.edge_contracts import INCOMPLETE, edge_contract_readiness
from app.services.package_writer import PackageWriteError, write_package, write_package_result
from app.services.project_file_service import deserialize_project, restore_session


def _csv_layout(*, delimiter: str = ",", has_header_row: bool = False) -> str:
    return (
        "format: csv\n"
        f'delimiter: "{delimiter}"\n'
        f"has_header_row: {'true' if has_header_row else 'false'}\n"
        "record_types:\n"
        "  data:\n"
        "    fields:\n"
        "      - name: account_id\n"
        "        column: 1\n"
        "        type: string\n"
        "      - name: status\n"
        "        column: 2\n"
        "        type: string\n"
    )


def _full_session() -> ProjectSession:
    """Independent scalar fixture: mapping, file layout, staging and rule seams.

    Account is a generic test entity, not a reduced external specification.
    URL-only provenance is intentional; real cached-ingestion tests supply their
    own matching contract and prove no silent sample fallback.
    """
    s = ProjectSession(
        app_name="Synthetic Records", bounded_context="records",
        target_profile="springboot-legacy-compatible",
        selected_entity_names=["Account"],
        classified_entities=[ClassifiedEntity(name="Account", fields=[
            ClassifiedField(name="accountId", type="string", is_id=True),
            ClassifiedField(name="label", type="string"),
            ClassifiedField(name="category", type="string"),
            ClassifiedField(name="status", type="string"),
        ])],
    )
    s.upstream_interfaces = [UpstreamInterface(
        name="synthetic-account-api", system="Synthetic", type="rest-json",
        version="1.0", spec_url="https://example.com/synthetic-account.json",
        entity_name="Account",
        operations=[OperationSample(
            name="createAccount",
            request_sample_path="upstream/create-account-request.json",
            response_sample_path="upstream/create-account-response.json",
            request_sample_content='{"label":"Synthetic desk","category":"LOCAL"}',
            response_sample_content='{"accountId":"SYNTH-17","status":"NEW"}',
        )],
        operation_mappings=[OperationMapping(
            name="createAccount",
            request_mappings=[
                FieldMapping(source="label", target="Account.label"),
                FieldMapping(source="category", target="Account.category"),
            ],
            response_mappings=[
                FieldMapping(source="accountId", target="Account.accountId"),
                FieldMapping(source="status", target="Account.status"),
            ],
        )], mapping_path="upstream/synthetic-account-api-mapping.yaml",
    )]
    s.downstream_interfaces = [DownstreamInterface(
        name="eod-handoff-file", system="SyntheticFile", type="file-fixed-width",
        version="v1", spec="downstream/eod-handoff-file-layout.yaml",
        entity_name="Account",
        layout_fields=[LayoutField(name="account_id", start=1, length=24)],
        field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
        mapping_path="downstream/eod-handoff-file-mapping.yaml",
    )]
    s.data_handoffs = [DataHandoff(
        name="account-staging-table", system="SyntheticStage", type="staging-table",
        version="v1", spec="data-handoffs/account-staging-table.sql",
        ddl_content="CREATE TABLE synthetic_stage (record_id VARCHAR(24) NOT NULL);",
        table_name="synthetic_stage", entity_name="Account",
        field_mappings=[FieldMapping(source="Account.accountId", target="record_id")],
        mapping_path="data-handoffs/account-staging-table-mapping.yaml",
    )]
    s.entity_rules = [EntityRules(entity_name="Account", rules=[
        RuleEntry(field="status", type="default", value="NEW"),
        RuleEntry(field="category", type="allowed-values", values=["LOCAL", "SHARED"]),
    ], file_path="rules/account-business-rules.yaml")]
    s.legacy_notes = "# Notes\n\n- Synthetic compatibility note."
    s.legacy_slug = "records"
    return s


def test_package_file_tree():
    s = _full_session()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        written = write_package(s, root)
        project_dir = root / "records"

        assert "app-definition.yaml" in written
        assert "completeness-report.md" in written
        assert "assessment-report.json" in written
        assert "studio-project.json" in written
        assert (project_dir / "app-definition.yaml").exists()
        assert (project_dir / "completeness-report.md").exists()
        assert (project_dir / "studio-project.json").exists()


def test_export_is_side_effect_free_for_url_backed_specs():
    """Regression: a successful export must not push the package-local spec
    back into the live session for a URL-backed interface.

    `UpstreamInterface` documents "Exactly one of spec or spec_url", and the
    propagation block in package_writer says spec changes on URL-backed
    interfaces are intentionally not propagated. The `not orig.spec` guard
    did not enforce that -- a URL-backed interface has an empty spec by
    definition, so the packaging copy's package-relative path sailed through
    and the session ended up holding both. The next export then failed with
    "both spec and spec_url are set", and recovery needed a Step 2 re-fetch
    plus a Step 3 re-save. Found by the browser-driven end-to-end drive.
    """
    s = _full_session()
    upstream = s.upstream_interfaces[0]
    assert upstream.spec_url and not upstream.spec, "fixture must be URL-backed to discriminate"
    original_spec_url = upstream.spec_url
    # The package only copies a URL-backed spec locally when the fetched
    # content is cached on the session (package_writer's `elif iface.spec_url
    # and not iface.spec and working.raw_spec_content` branch). Without this
    # the propagation path is never reached and the test would be vacuous.
    s.raw_spec_content = '{"openapi": "3.0.0", "info": {"title": "t", "version": "1"}, "paths": {}}'
    s.raw_spec_filename = "synthetic-account.json"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        written = write_package(s, root)

        # The package still gets its own copied, package-relative spec ...
        copied = [rel for rel in written if rel.startswith("contracts/") and "-spec" in rel]
        assert copied, f"package must copy the fetched spec locally; wrote {sorted(written)}"

        # ... while the live session keeps ONLY spec_url.
        assert s.upstream_interfaces[0].spec_url == original_spec_url
        assert not s.upstream_interfaces[0].spec, (
            "export leaked the package-local spec into the live session; "
            "the next export would fail the exactly-one invariant"
        )

        # And the whole point: exporting again works, with no recovery step.
        write_package(s, root)
        assert s.upstream_interfaces[0].spec_url == original_spec_url
        assert not s.upstream_interfaces[0].spec


def test_package_blocks_mapping_target_missing_from_canonical_entity():
    s = _full_session()
    s.upstream_interfaces[0].operation_mappings[0].request_mappings.append(
        FieldMapping(source="currency_code", target="Account.currency_code")
    )

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError, match="Account.currency_code"):
            write_package(s, Path(tmp))


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (" label", "Account.label"),
        ("label", " Account.label "),
        ("label", "   "),
    ],
)
def test_package_blocks_operation_mapping_paths_with_surrounding_whitespace(source, target):
    s = _full_session()
    mapping = s.upstream_interfaces[0].operation_mappings[0].request_mappings[0]
    mapping.source = source
    mapping.target = target

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError, match="whitespace"):
            write_package(s, Path(tmp))


def test_package_includes_openable_studio_project_snapshot():
    s = _full_session()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"

        raw = (project_dir / "studio-project.json").read_text(encoding="utf-8")
        project = deserialize_project(raw)
        restored = ProjectSession()
        restore_session(project, restored)
        revision = restored.ks_workspace_state.manifest_revisions[-1]

        assert restored.app_name == "Synthetic Records"
        assert restored.bounded_context == "records"
        assert restored.selected_entity_names == ["Account"]
        assert restored.last_export_path == str(project_dir)
        assert revision.revision_id
        assert revision.manifest_hash
        assert revision.export_path == str(project_dir)


def test_package_writes_edge_contract_artifacts():
    s = ProjectSession()
    s.app_name = "Edge Contracts"
    s.bounded_context = "edge-contracts"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            xsd_content="<xs:schema xmlns:xs=\"http://www.w3.org/2001/XMLSchema\"/>",
            root_element="acct:Account",
        ),
        UpstreamInterface(
            name="account-soap",
            type="soap-wsdl",
            wsdl_path="contracts/account.wsdl",
            wsdl_content="<definitions/>",
        ),
    ]
    s.downstream_interfaces = [
        DownstreamInterface(
            name="account-csv",
            type="file-csv",
            spec="downstream/account-csv-layout.yaml",
            spec_content=_csv_layout(),
            mapping_path="downstream/account-csv-mapping.yaml",
            field_mappings=[FieldMapping(source="Account.accountId", target="account_id")],
            sample_path="downstream/account-csv-sample.csv",
            sample_content="accountId,status\nA1,ACTIVE\n",
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        written = write_package(s, root)
        project_dir = root / "edge-contracts"
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text(encoding="utf-8"))

        assert "contracts/account.xsd" in written
        assert "contracts/account.wsdl" in written
        assert "downstream/account-csv-layout.yaml" in written
        assert "downstream/account-csv-mapping.yaml" in written
        assert "downstream/account-csv-sample.csv" in written
        assert manifest["upstream_interfaces"][0]["xsd_path"] == "contracts/account.xsd"
        assert manifest["upstream_interfaces"][1]["wsdl_path"] == "contracts/account.wsdl"
        assert manifest["downstream_interfaces"][0]["type"] == "file-csv"
        assert manifest["downstream_interfaces"][0]["mapping"] == "downstream/account-csv-mapping.yaml"
        assert manifest["downstream_interfaces"][0]["samples"] == ["downstream/account-csv-sample.csv"]


def test_package_writes_upstream_file_canonical_mapping():
    s = ProjectSession()
    s.app_name = "File Inbound"
    s.bounded_context = "file-inbound"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content="format: csv\nfields: []\n",
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="account_id", target="accountId"),
                FieldMapping(source="status", target="Account.status"),
            ],
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        project_dir = result.project_dir
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text(encoding="utf-8"))
        mapping_path = "upstream/account-csv-in-mapping.yaml"
        mapping = yaml.safe_load((project_dir / mapping_path).read_text(encoding="utf-8"))

        assert mapping_path in result.written
        assert manifest["upstream_interfaces"][0]["mapping"] == mapping_path
        assert mapping == {
            "entity": "Account",
            "direction": "inbound",
            "field_mappings": [
                {"source": "account_id", "target": "Account.accountId"},
                {"source": "status", "target": "Account.status"},
            ],
        }


def test_package_preserves_csv_delimiter_and_header_in_layout_specs():
    s = ProjectSession()
    s.app_name = "CSV Controls"
    s.bounded_context = "csv-controls"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-csv-in",
            type="file-csv",
            spec="upstream/account-csv-layout.yaml",
            spec_content='format: csv\ndelimiter: "|"\nhas_header_row: true\nfields: []\n',
        )
    ]
    s.downstream_interfaces = [
        DownstreamInterface(
            name="account-csv-out",
            type="file-csv",
            spec="downstream/account-csv-layout.yaml",
            spec_content=_csv_layout(delimiter="~", has_header_row=False),
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        project_dir = result.project_dir
        upstream_spec = (project_dir / "upstream/account-csv-layout.yaml").read_text(encoding="utf-8")
        downstream_spec = (project_dir / "downstream/account-csv-layout.yaml").read_text(encoding="utf-8")

        assert "upstream/account-csv-layout.yaml" in result.written
        assert "downstream/account-csv-layout.yaml" in result.written
        assert 'delimiter: "|"' in upstream_spec
        assert "has_header_row: true" in upstream_spec
        assert 'delimiter: "~"' in downstream_spec
        assert "has_header_row: false" in downstream_spec


def test_package_upgrades_legacy_downstream_csv_without_mutating_project_state():
    session = ProjectSession(
        app_name="Legacy CSV",
        bounded_context="legacy-csv",
        target_profile="springboot-legacy-compatible",
        downstream_interfaces=[
            DownstreamInterface(
                name="legacy-csv-out",
                type="file-csv",
                spec="downstream/legacy-layout.yaml",
                spec_content=(
                    "# legacy authoring\n"
                    "format: csv\n"
                    "fields:\n"
                    "  - name: account_id\n"
                    "  - name: status\n"
                ),
            )
        ],
    )
    original = session.downstream_interfaces[0].spec_content

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(session, Path(tmp))
        written_layout = (result.project_dir / "downstream/legacy-layout.yaml").read_text(
            encoding="utf-8"
        )

    parsed = yaml.safe_load(written_layout)
    assert "# legacy authoring" in written_layout
    assert parsed["record_types"]["data"]["fields"] == [
        {"name": "account_id", "column": 1},
        {"name": "status", "column": 2},
    ]
    assert session.downstream_interfaces[0].spec_content == original


def test_package_blocks_malformed_downstream_csv_layout():
    session = ProjectSession(
        app_name="Bad CSV",
        bounded_context="bad-csv",
        downstream_interfaces=[
            DownstreamInterface(
                name="bad-csv",
                type="file-csv",
                spec="downstream/bad-layout.yaml",
                spec_content="record_types: [",
            )
        ],
    )

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError, match="Malformed CSV layout/spec YAML"):
            write_package_result(session, Path(tmp))


def test_package_and_readiness_block_quoted_csv_columns():
    iface = DownstreamInterface(
        name="quoted-column-csv",
        type="file-csv",
        spec="downstream/quoted-column-layout.yaml",
        spec_content=(
            "format: csv\n"
            "record_types:\n"
            "  data:\n"
            "    fields:\n"
            '      - {name: account_id, column: "1"}\n'
        ),
    )
    session = ProjectSession(
        app_name="Quoted CSV",
        bounded_context="quoted-csv",
        downstream_interfaces=[iface],
    )

    readiness = edge_contract_readiness(iface, direction="downstream", session=session)
    assert readiness.status == INCOMPLETE
    assert readiness.will_export is False
    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError, match="positive integer column"):
            write_package_result(session, Path(tmp))


def test_package_writes_seeded_file_mappings_same_as_manual_rows():
    s = ProjectSession()
    s.app_name = "Seeded File Mapping"
    s.bounded_context = "seeded-file-mapping"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-fixed-in",
            type="file-fixed-width",
            spec="upstream/account-fixed-layout.yaml",
            spec_content=(
                "format: fixed-width\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: account_id\n"
                "        position: 1\n"
                "        length: 12\n"
            ),
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="account_id", target="Account.accountId"),
            ],
        )
    ]
    s.downstream_interfaces = [
        DownstreamInterface(
            name="account-fixed-out",
            type="file-fixed-width",
            spec="downstream/account-fixed-layout.yaml",
            spec_content=(
                "format: fixed-width\n"
                "record_types:\n"
                "  data:\n"
                "    fields:\n"
                "      - name: account_id\n"
                "        position: 1\n"
                "        length: 12\n"
            ),
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="Account.accountId", target="account_id"),
            ],
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        project_dir = result.project_dir
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text(encoding="utf-8"))
        upstream_mapping = yaml.safe_load(
            (project_dir / "upstream/account-fixed-in-mapping.yaml").read_text(encoding="utf-8")
        )
        downstream_mapping = yaml.safe_load(
            (project_dir / "downstream/account-fixed-out-mapping.yaml").read_text(encoding="utf-8")
        )

        assert manifest["upstream_interfaces"][0]["mapping"] == "upstream/account-fixed-in-mapping.yaml"
        assert manifest["downstream_interfaces"][0]["mapping"] == "downstream/account-fixed-out-mapping.yaml"
        assert upstream_mapping["field_mappings"] == [
            {"source": "account_id", "target": "Account.accountId"}
        ]
        assert downstream_mapping["field_mappings"] == [
            {"source": "Account.accountId", "target": "account_id"}
        ]


def test_package_writes_xml_canonical_mappings():
    s = ProjectSession()
    s.app_name = "XML Runtime"
    s.bounded_context = "xml-runtime"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml-in",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            xsd_content="<xs:schema xmlns:xs=\"http://www.w3.org/2001/XMLSchema\"/>",
            root_element="AccountMessage",
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="accountId", target="accountId"),
                FieldMapping(source="sourceSystem", target="Account.sourceSystem"),
            ],
        )
    ]
    s.downstream_interfaces = [
        DownstreamInterface(
            name="account-xml-out",
            type="xml-xsd",
            xsd_path="contracts/account-out.xsd",
            xsd_content="<xs:schema xmlns:xs=\"http://www.w3.org/2001/XMLSchema\"/>",
            root_element="AccountMessage",
            entity_name="Account",
            field_mappings=[
                FieldMapping(source="Account.accountId", target="accountId"),
                FieldMapping(source="Account.sourceSystem", target="sourceSystem"),
            ],
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        project_dir = result.project_dir
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text(encoding="utf-8"))
        upstream_mapping = yaml.safe_load(
            (project_dir / "upstream/account-xml-in-mapping.yaml").read_text(encoding="utf-8")
        )
        downstream_mapping = yaml.safe_load(
            (project_dir / "downstream/account-xml-out-mapping.yaml").read_text(encoding="utf-8")
        )

        assert "upstream/account-xml-in-mapping.yaml" in result.written
        assert "downstream/account-xml-out-mapping.yaml" in result.written
        assert manifest["upstream_interfaces"][0]["mapping"] == "upstream/account-xml-in-mapping.yaml"
        assert manifest["downstream_interfaces"][0]["mapping"] == "downstream/account-xml-out-mapping.yaml"
        assert upstream_mapping == {
            "entity": "Account",
            "direction": "inbound",
            "field_mappings": [
                {"source": "accountId", "target": "Account.accountId"},
                {"source": "sourceSystem", "target": "Account.sourceSystem"},
            ],
        }
        assert downstream_mapping == {
            "entity": "Account",
            "direction": "outbound",
            "field_mappings": [
                {"source": "Account.accountId", "target": "accountId"},
                {"source": "Account.sourceSystem", "target": "sourceSystem"},
            ],
        }


def test_package_reference_only_edge_contract_exports_with_warning():
    s = ProjectSession()
    s.app_name = "Edge Contracts"
    s.bounded_context = "edge-contracts"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="account-xml",
            type="xml-xsd",
            xsd_path="contracts/account.xsd",
            root_element="acct:Account",
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        project_dir = result.project_dir
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text(encoding="utf-8"))

        assert manifest["upstream_interfaces"][0]["xsd_path"] == "contracts/account.xsd"
        assert not (project_dir / "contracts/account.xsd").exists()
        assert any("no uploaded artifact content" in warning for warning in result.warnings)


def test_package_writes_upstream_soap_operation_mapping():
    s = ProjectSession()
    s.app_name = "SOAP Inbound"
    s.bounded_context = "soap-inbound"
    s.target_profile = "springboot-legacy-compatible"
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
    s.upstream_interfaces = [
        UpstreamInterface(
            name="customer-soap-service",
            type="soap-wsdl",
            wsdl_path="contracts/customer-service.wsdl",
            wsdl_content="<definitions/>",
            service="CustomerService",
            port="CustomerServicePort",
            binding="CustomerServiceBinding",
            selected_operation_name="getCustomer",
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        project_dir = result.project_dir
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text(encoding="utf-8"))
        mapping_path = "mappings/customer-soap-service-operation-mapping.yaml"
        mapping = yaml.safe_load((project_dir / mapping_path).read_text(encoding="utf-8"))
        completeness = (project_dir / "completeness-report.md").read_text(encoding="utf-8")

        assert mapping_path in result.written
        assert "operations" not in manifest["upstream_interfaces"][0]
        assert manifest["upstream_interfaces"][0]["mapping"] == mapping_path
        assert mapping == {
            "operation_mappings": [
                {
                    "operation": "getCustomer",
                    "mode": "adapter_only",
                    "handler_method": "handleGetCustomer",
                }
            ]
        }
        assert "selected inbound SOAP operation 'getCustomer'" in completeness
        assert "needs at least one sample" not in completeness


def test_package_writes_sanitized_soap_operation_handler_name():
    s = ProjectSession()
    s.app_name = "SOAP Inbound"
    s.bounded_context = "soap-inbound"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="numeric-soap-service",
            type="soap-wsdl",
            wsdl_path="contracts/numeric.wsdl",
            selected_operation_name="123-get_customer",
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        mapping = yaml.safe_load(
            (result.project_dir / "mappings/numeric-soap-service-operation-mapping.yaml").read_text(
                encoding="utf-8"
            )
        )

        assert mapping["operation_mappings"][0]["handler_method"] == "handleOperation123GetCustomer"


def test_package_writes_upstream_soap_canonical_operation_mapping():
    s = ProjectSession()
    s.app_name = "SOAP Inbound"
    s.bounded_context = "soap-inbound"
    s.target_profile = "springboot-legacy-compatible"
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
    s.upstream_interfaces = [
        UpstreamInterface(
            name="customer-soap-service",
            type="soap-wsdl",
            wsdl_path="contracts/customer-service.wsdl",
            wsdl_content="<definitions/>",
            service="CustomerService",
            port="CustomerServicePort",
            binding="CustomerServiceBinding",
            selected_operation_name="getCustomer",
            soap_operation_mode="canonical",
            soap_handler_method="handleGetCustomer",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Customer",
                lookup_field="customerId",
                request_path="/GetCustomerRequest/customerId",
                response_mappings=[
                    SoapResponseMapping(
                        source="Customer.customerId",
                        target_path="/GetCustomerResponse/customerId",
                    ),
                    SoapResponseMapping(
                        source="Customer.status",
                        target_path="/GetCustomerResponse/status",
                    ),
                ],
                not_found_fault="customerFault",
                not_found_message="Customer not found",
            ),
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        mapping_path = "mappings/customer-soap-service-operation-mapping.yaml"
        mapping = yaml.safe_load((result.project_dir / mapping_path).read_text(encoding="utf-8"))

        assert mapping_path in result.written
        assert mapping["operation_mappings"][0] == {
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
        assert "handler_method" not in mapping["operation_mappings"][0]


def test_package_blocks_canonical_soap_without_verified_persistence_model():
    s = ProjectSession()
    s.app_name = "SOAP Inbound"
    s.bounded_context = "soap-inbound"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="customer-soap-service",
            type="soap-wsdl",
            wsdl_path="contracts/customer-service.wsdl",
            selected_operation_name="getCustomer",
            soap_operation_mode="canonical",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Customer",
                lookup_field="customerId",
                request_path="/GetCustomerRequest/customerId",
                response_mappings=[
                    SoapResponseMapping(
                        source="Customer.customerId",
                        target_path="/GetCustomerResponse/customerId",
                    )
                ],
            ),
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError, match="known canonical entity"):
            write_package_result(s, Path(tmp))


def test_package_blocks_restored_canonical_soap_with_invalid_response_mapping():
    s = ProjectSession()
    s.app_name = "SOAP Inbound"
    s.bounded_context = "soap-inbound"
    s.target_profile = "springboot-legacy-compatible"
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
    s.upstream_interfaces = [
        UpstreamInterface(
            name="customer-soap-service",
            type="soap-wsdl",
            wsdl_path="contracts/customer-service.wsdl",
            selected_operation_name="getCustomer",
            soap_operation_mode="canonical",
            soap_canonical_operation=SoapCanonicalOperationConfig(
                entity="Customer",
                lookup_field="customerId",
                request_path="/GetCustomerRequest/customerId",
                response_mappings=[
                    SoapResponseMapping(
                        source="Customer.missingStatus",
                        target_path="/GetCustomerResponse/status",
                    )
                ],
            ),
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError, match="missingStatus"):
            write_package_result(s, Path(tmp))


def test_package_writes_downstream_soap_adapter_operation_mapping():
    s = ProjectSession()
    s.app_name = "SOAP Outbound"
    s.bounded_context = "soap-outbound"
    s.target_profile = "springboot-legacy-compatible"
    s.downstream_interfaces = [
        DownstreamInterface(
            name="customer-soap-client",
            type="soap-wsdl",
            wsdl_path="contracts/customer-client.wsdl",
            wsdl_content="<definitions/>",
            service="CustomerSyncService",
            port="CustomerSyncServicePort",
            binding="CustomerSyncServiceBinding",
            selected_operation_name="syncCustomer",
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        mapping_path = "mappings/customer-soap-client-operation-mapping.yaml"
        manifest = yaml.safe_load((result.project_dir / "app-definition.yaml").read_text(encoding="utf-8"))
        mapping = yaml.safe_load((result.project_dir / mapping_path).read_text(encoding="utf-8"))

        assert mapping_path in result.written
        assert manifest["downstream_interfaces"][0]["mapping"] == mapping_path
        assert mapping == {
            "operation_mappings": [
                {
                    "operation": "syncCustomer",
                    "mode": "adapter_only",
                }
            ]
        }


def test_package_writes_downstream_soap_canonical_invoke_by_id_mapping():
    s = ProjectSession()
    s.app_name = "SOAP Outbound"
    s.bounded_context = "soap-outbound"
    s.target_profile = "springboot-legacy-compatible"
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
            wsdl_content="<definitions/>",
            service="CustomerSyncService",
            port="CustomerSyncServicePort",
            binding="CustomerSyncServiceBinding",
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
    ]

    with tempfile.TemporaryDirectory() as tmp:
        result = write_package_result(s, Path(tmp))
        mapping_path = "mappings/customer-soap-client-operation-mapping.yaml"
        manifest = yaml.safe_load((result.project_dir / "app-definition.yaml").read_text(encoding="utf-8"))
        mapping = yaml.safe_load((result.project_dir / mapping_path).read_text(encoding="utf-8"))

        assert result.warnings == []
        assert mapping_path in result.written
        assert manifest["downstream_interfaces"][0]["mapping"] == mapping_path
        assert mapping["operation_mappings"][0] == {
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


def test_package_blocks_downstream_canonical_soap_without_verified_persistence_model():
    s = ProjectSession()
    s.app_name = "SOAP Outbound"
    s.bounded_context = "soap-outbound"
    s.target_profile = "springboot-legacy-compatible"
    s.downstream_interfaces = [
        DownstreamInterface(
            name="customer-soap-client",
            type="soap-wsdl",
            wsdl_path="contracts/customer-client.wsdl",
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

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError, match="known canonical entity"):
            write_package_result(s, Path(tmp))


def test_package_blocks_downstream_canonical_soap_duplicate_mapping_rows():
    s = ProjectSession()
    s.app_name = "SOAP Outbound"
    s.bounded_context = "soap-outbound"
    s.target_profile = "springboot-legacy-compatible"
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
            selected_operation_name="syncCustomer",
            soap_operation_mode="canonical",
            soap_canonical_invocation=SoapCanonicalInvocationConfig(
                entity="Customer",
                lookup_field="customerId",
                request_mappings=[
                    SoapRequestMapping(source="Customer.customerId", target_path="/SyncCustomerRequest/customerId"),
                    SoapRequestMapping(source="Customer.status", target_path="/SyncCustomerRequest/customerId"),
                ],
                response_mappings=[
                    SoapReturnMapping(source_path="/SyncCustomerResponse/resultCode", target="resultCode"),
                    SoapReturnMapping(source_path="/SyncCustomerResponse/message", target="resultCode"),
                ],
            ),
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError, match="used more than once"):
            write_package_result(s, Path(tmp))


def test_package_blocks_incomplete_edge_contract_export():
    s = ProjectSession()
    s.app_name = "Edge Contracts"
    s.bounded_context = "edge-contracts"
    s.target_profile = "springboot-legacy-compatible"
    s.downstream_interfaces = [
        DownstreamInterface(name="csv-out", type="file-csv")
    ]

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError) as exc:
            write_package(s, Path(tmp))

    assert "csv-out" in str(exc.value)
    assert "layout/spec path" in str(exc.value)


def test_package_rejects_edge_contract_path_traversal():
    s = ProjectSession()
    s.app_name = "Edge Contracts"
    s.bounded_context = "edge-contracts"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="unsafe-xml",
            type="xml-xsd",
            xsd_path="../unsafe.xsd",
            xsd_content="<xs:schema/>",
            root_element="Root",
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError) as exc:
            write_package(s, Path(tmp))

    assert "unsafe-xml" in str(exc.value)
    assert "valid artifact path" in str(exc.value)


def test_package_rejects_url_like_edge_contract_artifact_path():
    s = ProjectSession()
    s.app_name = "Edge Contracts"
    s.bounded_context = "edge-contracts"
    s.target_profile = "springboot-legacy-compatible"
    s.upstream_interfaces = [
        UpstreamInterface(
            name="url-xml",
            type="xml-xsd",
            xsd_path="https://example.com/schema.xsd",
            root_element="Root",
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        with pytest.raises(PackageWriteError) as exc:
            write_package(s, Path(tmp))

    assert "url-xml" in str(exc.value)
    assert "valid artifact path" in str(exc.value)


def test_written_manifest_contains_v2_contract_fields():
    """Written app-definition.yaml must include schema_version and app_archetype."""
    s = _full_session()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        manifest = yaml.safe_load((root / "records" / "app-definition.yaml").read_text())
        assert manifest["schema_version"] == "2.0", "schema_version must be '2.0'"
        assert manifest["app_archetype"] == "crud", "app_archetype must be 'crud'"


@pytest.mark.parametrize("archetype", ["crud", "passthrough-router", "kafka-integration"])
def test_package_writer_emits_manifest_v2_for_every_archetype(tmp_path, archetype):
    session = ProjectSession(
        app_name="Manifest V2 Test",
        bounded_context=f"manifest-v2-{archetype}",
        app_archetype=archetype,
    )

    result = write_package_result(session, tmp_path)
    manifest = yaml.safe_load(
        (result.project_dir / "app-definition.yaml").read_text(encoding="utf-8")
    )

    assert manifest["schema_version"] == "2.0"
    assert manifest["app_archetype"] == archetype


def test_written_manifest_preserves_enterprise_postgres_java17_target_profile():
    """Written app-definition.yaml must pass through the new Engine target profile unchanged."""
    s = _full_session()
    s.target_profile = "springboot-enterprise-postgres-java17"
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        manifest = yaml.safe_load((root / "records" / "app-definition.yaml").read_text())
        assert manifest["target_profile"] == "springboot-enterprise-postgres-java17"


def test_manifest_paths_valid():
    """All paths in the manifest must exist on disk."""
    s = _full_session()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"

        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text())

        # Check all upstream paths
        for iface in manifest.get("upstream_interfaces", []):
            if iface.get("spec"):
                assert (project_dir / iface["spec"]).exists(), f"Missing: {iface['spec']}"
            if iface.get("mapping"):
                assert (project_dir / iface["mapping"]).exists(), f"Missing: {iface['mapping']}"
            for op in iface.get("operations", []):
                if op.get("request_sample"):
                    assert (project_dir / op["request_sample"]).exists()
                if op.get("response_sample"):
                    assert (project_dir / op["response_sample"]).exists()

        # Check rule paths
        for rule_path in manifest.get("rules", []):
            assert (project_dir / rule_path).exists(), f"Missing rule: {rule_path}"


def test_upstream_mapping_yaml_shape():
    s = _full_session()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"
        mapping = yaml.safe_load(
            (project_dir / "upstream/synthetic-account-api-mapping.yaml").read_text()
        )
        assert mapping["interface"] == "synthetic-account-api"
        assert mapping["entity"] == "Account"
        assert "operations" in mapping
        op = mapping["operations"][0]
        assert op["name"] == "createAccount"
        assert "request_mappings" in op
        assert "response_mappings" in op


def test_downstream_mapping_shape():
    s = _full_session()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"
        mapping = yaml.safe_load(
            (project_dir / "downstream/eod-handoff-file-mapping.yaml").read_text()
        )
        assert mapping["interface"] == "eod-handoff-file"
        assert mapping["entity"] == "Account"
        assert "field_mappings" in mapping
        assert "table" not in mapping


def test_package_writes_all_explicit_downstream_layouts_and_mappings():
    s = _full_session()
    s.downstream_interfaces = [
        DownstreamInterface(
            name="customer-eod-file",
            type="file-fixed-width",
            entity_name="Customer",
            spec="downstream/customer-eod-file-layout.yaml",
            layout_fields=[
                LayoutField(name="customer_id", start=1, length=36),
                LayoutField(name="country_code", start=37, length=2),
                LayoutField(name="kyc_status_flag", start=39, length=1),
            ],
            field_mappings=[
                FieldMapping(source="Customer.customerId", target="customer_id"),
                FieldMapping(source="Customer.countryCode", target="country_code"),
                FieldMapping(source="Customer.kycStatusFlag", target="kyc_status_flag"),
            ],
            mapping_path="downstream/customer-eod-file-mapping.yaml",
        ),
        DownstreamInterface(
            name="account-eod-file",
            type="file-fixed-width",
            entity_name="Account",
            spec="downstream/account-eod-file-layout.yaml",
            layout_fields=[
                LayoutField(name="account_number", start=1, length=18),
                LayoutField(name="sort_code", start=19, length=6),
                LayoutField(name="routing_number", start=25, length=9),
            ],
            field_mappings=[
                FieldMapping(source="Account.accountNumber", target="account_number"),
                FieldMapping(source="Account.sortCode", target="sort_code"),
                FieldMapping(source="Account.routingNumber", target="routing_number"),
            ],
            mapping_path="downstream/account-eod-file-mapping.yaml",
        ),
        DownstreamInterface(
            name="transaction-eod-file",
            type="file-fixed-width",
            entity_name="Transaction",
            spec="downstream/transaction-eod-file-layout.yaml",
            layout_fields=[
                LayoutField(name="source_system_code", start=1, length=8),
                LayoutField(name="payment_amount_minor", start=9, length=12),
                LayoutField(name="payment_status", start=21, length=12),
            ],
            field_mappings=[
                FieldMapping(source="Transaction.sourceSystemCode", target="source_system_code"),
                FieldMapping(source="Transaction.paymentAmountMinor", target="payment_amount_minor"),
                FieldMapping(source="Transaction.paymentStatus", target="payment_status"),
            ],
            mapping_path="downstream/transaction-eod-file-mapping.yaml",
        ),
    ]
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"

        expected_fields = {
            "customer-eod-file": ["customer_id", "country_code", "kyc_status_flag"],
            "account-eod-file": ["account_number", "sort_code", "routing_number"],
            "transaction-eod-file": ["source_system_code", "payment_amount_minor", "payment_status"],
        }
        for interface_name, fields in expected_fields.items():
            layout = yaml.safe_load(
                (project_dir / f"downstream/{interface_name}-layout.yaml").read_text()
            )
            mapping = yaml.safe_load(
                (project_dir / f"downstream/{interface_name}-mapping.yaml").read_text()
            )
            layout_fields = layout["record_types"]["data"]["fields"]
            assert [field["name"] for field in layout_fields] == fields
            assert [field["position"] for field in layout_fields] == [
                row.start
                for row in next(
                    iface for iface in s.downstream_interfaces if iface.name == interface_name
                ).layout_fields
            ]
            assert [item["target"] for item in mapping["field_mappings"]] == fields


def test_handoff_mapping_uses_table_key():
    s = _full_session()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"
        mapping = yaml.safe_load(
            (project_dir / "data-handoffs/account-staging-table-mapping.yaml").read_text()
        )
        assert mapping["table"] == "synthetic_stage"
        assert mapping["entity"] == "Account"
        assert "interface" not in mapping


def test_rule_file_generated():
    s = _full_session()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"
        rules = yaml.safe_load(
            (project_dir / "rules/account-business-rules.yaml").read_text()
        )
        assert rules["entity"] == "Account"
        types = [r["type"] for r in rules["rules"]]
        assert "default" in types
        assert "allowed-values" in types


def test_rule_file_generated_for_field_comparison():
    s = _full_session()
    s.entity_rules[0].rules.append(
        RuleEntry(
            field="balance",
            type="field-comparison",
            operator=">=",
            compare_to_field="minimumBalance",
        )
    )
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"
        rules = yaml.safe_load(
            (project_dir / "rules/account-business-rules.yaml").read_text()
        )
        field_comp = next(r for r in rules["rules"] if r["type"] == "field-comparison")
        assert field_comp["field"] == "balance"
        assert field_comp["operator"] == ">="
        assert field_comp["compare-to-field"] == "minimumBalance"


def test_kafka_router_authored_transform_rows_write_referenced_files():
    s = ProjectSession()
    s.app_name = "Payment Router"
    s.bounded_context = "payments"
    s.app_archetype = "kafka-integration"
    s.target_profile = "springboot-standard-enterprise"
    s.kafka_config = KafkaConfig(consumer_group="payment-router-group")
    s.kafka_topic_pairs = [
        KafkaTopicPair(
            route_name="payment-posted",
            upstream_topic="abc.payments.posted.v1",
            upstream_schema_content='{"type":"object","properties":{"paymentId":{"type":"string"},"status":{"type":"string"},"amount":{"type":"number"}}}',
            downstream_topic="xyz.ledger.entries.v1",
            downstream_schema_content='{"type":"object","properties":{"transactionId":{"type":"string"},"decisionCode":{"type":"string"},"amountMinor":{"type":"integer"}}}',
        )
    ]
    s.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config={
                "upstream_topics": [
                    {
                        "id": "u1",
                        "name": "abc.payments.posted.v1",
                        "consumer_group": "payment-router-group",
                        "source_system_extraction": {
                            "mode": "header",
                            "header_key": "X-Source-System",
                        },
                        "reply_destination_extraction": {
                            "mode": "header",
                            "header_key": "X-Reply-To",
                        },
                    }
                ],
                "inbound_schema": {"file": "schemas/payment-posted-upstream.json"},
                "routing_rules": {
                    "routing_fields": [{"name": "country", "json_path": "$.country"}],
                    "rules": [
                        {
                            "id": "uk",
                            "conditions": [{"field": "country", "operator": "eq", "value": "UK"}],
                            "target": "ledger-core",
                        }
                    ],
                    "default_target": "ledger-core",
                },
                "targets": [
                    {
                        "id": "ledger-core",
                        "request_topic": "xyz.ledger.entries.v1",
                        "response_topic": "xyz.ledger.entries.reply.v1",
                        "request_schema": {"file": "schemas/payment-posted-downstream.json"},
                        "response_schema": {"file": "schemas/payment-posted-target-response.json"},
                        "request_transform": {"file": "transforms/payment-posted-request.yaml"},
                        "response_transform": {"file": "transforms/payment-posted-response.yaml"},
                        "retry": {
                            "max_attempts": 3,
                            "backoff_ms": 1000,
                            "dlq_topic": "xyz.ledger.entries.v1.dlq",
                        },
                        "timeout_ms": 30000,
                    }
                ],
                "outbound_schema": {"file": "schemas/payment-posted-outbound.json"},
                "nack_routing": {
                    "mode": "fixed",
                    "fixed_topic": "payment-router-nack",
                    "default_error_topic": "payment-router-error",
                },
            },
        )
    ]
    s.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="paymentId", target="transactionId"),
                        KafkaRouterTransformRow(
                            source="status",
                            target="decisionCode",
                            value_map={"APPROVED": "A", "DECLINED": "D"},
                        ),
                        KafkaRouterTransformRow(
                            source="amount",
                            target="amountMinor",
                            type_coercion="major_to_minor_units",
                        ),
                        KafkaRouterTransformRow(
                            target="currency",
                            default_value="USD",
                        ),
                    ],
                    response_transform_rows=[
                        KafkaRouterTransformRow(
                            source="processorStatus",
                            target="status",
                            value_map={"ACCEPTED": "APPROVED"},
                        )
                    ],
                )
            ],
        )
    ]

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "payments"
        (project_dir / "schemas").mkdir(parents=True)
        (project_dir / "schemas/payment-posted-target-response.json").write_text(
            '{"type":"object","properties":{"processorStatus":{"type":"string"}}}',
            encoding="utf-8",
        )
        (project_dir / "schemas/payment-posted-outbound.json").write_text(
            '{"type":"object","properties":{"status":{"type":"string"}}}',
            encoding="utf-8",
        )

        written = write_package(s, root)
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text())
        request_doc = yaml.safe_load((project_dir / "transforms/payment-posted-request.yaml").read_text())
        response_doc = yaml.safe_load((project_dir / "transforms/payment-posted-response.yaml").read_text())
        nack_routing = manifest["async_routes"][0]["router_config"]["nack_routing"]

        assert "transforms/payment-posted-request.yaml" in written
        assert "transforms/payment-posted-response.yaml" in written
        assert nack_routing["mode"] == "fixed"
        assert nack_routing["fixed_topic"] == "payment-router-nack"
        assert "per_source_system" not in nack_routing
        assert request_doc["transforms"][0] == {
            "source": "paymentId",
            "target": "transactionId",
        }
        assert request_doc["transforms"][1]["value_map"] == {
            "APPROVED": "A",
            "DECLINED": "D",
        }
        assert request_doc["transforms"][2]["type_coercion"] == "major_to_minor_units"
        assert request_doc["transforms"][3] == {
            "target": "currency",
            "default": "USD",
        }
        assert "default_value" not in request_doc["transforms"][3]
        assert response_doc["transforms"][0]["value_map"] == {
            "ACCEPTED": "APPROVED",
        }


def test_kafka_pure_router_writes_manifest_and_transform_files_without_topic_pairs(tmp_path):
    s = ProjectSession()
    s.app_name = "Payment Router"
    s.bounded_context = "payments"
    s.app_archetype = "kafka-integration"
    s.target_profile = "springboot-standard-enterprise"
    s.kafka_config = KafkaConfig(consumer_group="payment-router-group")
    s.kafka_topic_pairs = []
    s.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-posted",
            pattern="router",
            router_config={
                "upstream_topics": [
                    {
                        "id": "u1",
                        "name": "abc.payments.posted.v1",
                        "consumer_group": "payment-router-group",
                        "source_system_extraction": {
                            "mode": "header",
                            "header_key": "X-Source-System",
                        },
                        "reply_destination_extraction": {
                            "mode": "header",
                            "header_key": "X-Reply-To",
                        },
                    }
                ],
                "inbound_schema": {"file": "schemas/payment-posted-inbound.json"},
                "routing_rules": {
                    "routing_fields": [{"name": "country", "json_path": "$.country"}],
                    "rules": [
                        {
                            "id": "uk",
                            "conditions": [{"field": "country", "operator": "eq", "value": "UK"}],
                            "target": "ledger-core",
                        }
                    ],
                    "default_target": "ledger-core",
                },
                "targets": [
                    {
                        "id": "ledger-core",
                        "request_topic": "xyz.ledger.entries.v1",
                        "response_topic": "xyz.ledger.entries.reply.v1",
                        "request_schema": {"file": "schemas/payment-posted-request.json"},
                        "response_schema": {"file": "schemas/payment-posted-response.json"},
                        "request_transform": {"file": "transforms/payment-posted-request.yaml"},
                        "response_transform": {"file": "transforms/payment-posted-response.yaml"},
                        "retry": {
                            "max_attempts": 3,
                            "backoff_ms": 1000,
                            "dlq_topic": "xyz.ledger.entries.v1.dlq",
                        },
                    }
                ],
                "outbound_schema": {"file": "schemas/payment-posted-outbound.json"},
                "nack_routing": {
                    "mode": "default_error",
                    "default_error_topic": "payment-router-error",
                },
            },
        )
    ]
    s.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-posted",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="ledger-core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="paymentId", target="transactionId")
                    ],
                    response_transform_rows=[
                        KafkaRouterTransformRow(source="ledgerId", target="paymentId")
                    ],
                )
            ],
        )
    ]
    project_dir = tmp_path / "payments"
    for rel in [
        "schemas/payment-posted-inbound.json",
        "schemas/payment-posted-request.json",
        "schemas/payment-posted-response.json",
        "schemas/payment-posted-outbound.json",
    ]:
        path = project_dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"type":"object"}', encoding="utf-8")

    written = write_package(s, tmp_path)
    manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text())
    route = manifest["async_routes"][0]
    request_doc = yaml.safe_load((project_dir / "transforms/payment-posted-request.yaml").read_text())
    response_doc = yaml.safe_load((project_dir / "transforms/payment-posted-response.yaml").read_text())

    assert len(manifest["async_routes"]) == 1
    assert route["name"] == "payment-posted"
    assert route["pattern"] == "router"
    assert "router_config" in route
    assert "upstream_topic" not in route
    assert "downstream_topic" not in route
    assert "transform_mapping" not in route
    assert "upstream_reply_topic" not in route
    assert "downstream_reply_topic" not in route
    assert "response_transform_mapping" not in route
    assert "transforms/payment-posted-request.yaml" in written
    assert "transforms/payment-posted-response.yaml" in written
    assert request_doc["transforms"][0] == {"source": "paymentId", "target": "transactionId"}
    assert response_doc["transforms"][0] == {"source": "ledgerId", "target": "paymentId"}


def _multi_target_router_session() -> ProjectSession:
    s = ProjectSession()
    s.app_name = "Payment Router"
    s.bounded_context = "payments"
    s.app_archetype = "kafka-integration"
    s.target_profile = "springboot-standard-enterprise"
    s.kafka_config = KafkaConfig(consumer_group="payment-router-group")
    s.kafka_topic_pairs = [
        KafkaTopicPair(
            route_name="payment-router",
            upstream_topic="payments.router.requests.v1",
            upstream_schema_content='{"type":"object","properties":{"country":{"type":"string"},"appVersion":{"type":"string"}}}',
            downstream_topic="payments.generic.downstream.v1",
            downstream_schema_path="schemas/d2-eu-payment-request.json",
            downstream_schema_content='{"type":"object","properties":{"payment_id":{"type":"string"},"from_account":{"type":"string"}}}',
        )
    ]
    target_specs = [
        (
            "d1_us_core",
            "schemas/d1-us-payment-request.json",
            "schemas/d1-us-payment-response.json",
            "transforms/d1-us-request.yaml",
            "transforms/d1-us-response.yaml",
        ),
        (
            "d2_eu_core",
            "schemas/d2-eu-payment-request.json",
            "schemas/d2-eu-payment-response.json",
            "transforms/d2-eu-request.yaml",
            "transforms/d2-eu-response.yaml",
        ),
        (
            "d3_india_core",
            "schemas/d3-india-payment-request.json",
            "schemas/d3-india-payment-response.json",
            "transforms/d3-india-request.yaml",
            "transforms/d3-india-response.yaml",
        ),
    ]
    s.kafka_route_models = [
        KafkaRouteModel(
            route_name="payment-router",
            pattern="router",
            router_config={
                "upstream_topics": [
                    {
                        "id": "intake",
                        "name": "payments.router.requests.v1",
                        "consumer_group": "payment-router-group",
                        "source_system_extraction": {
                            "mode": "header",
                            "header_key": "X-Source-System",
                        },
                        "reply_destination_extraction": {
                            "mode": "header",
                            "header_key": "X-Reply-To",
                        },
                    }
                ],
                "inbound_schema": {"file": "schemas/payment-router-upstream.json"},
                "routing_rules": {
                    "routing_fields": [
                        {"name": "country", "json_path": "$.country"},
                        {"name": "appVersion", "json_path": "$.appVersion"},
                    ],
                    "rules": [
                        {
                            "id": "route-us-v1",
                            "conditions": [
                                {"field": "country", "operator": "eq", "value": "US"}
                            ],
                            "target": "d1_us_core",
                        },
                        {
                            "id": "route-de-v2",
                            "conditions": [
                                {"field": "country", "operator": "eq", "value": "DE"}
                            ],
                            "target": "d2_eu_core",
                        },
                        {
                            "id": "route-in-v1",
                            "conditions": [
                                {"field": "country", "operator": "eq", "value": "IN"}
                            ],
                            "target": "d3_india_core",
                        },
                    ],
                    "default_target": "d1_us_core",
                },
                "targets": [
                    {
                        "id": target_id,
                        "request_topic": f"{target_id}.request.v1",
                        "response_topic": f"{target_id}.response.v1",
                        "request_schema": {"file": request_schema},
                        "response_schema": {"file": response_schema},
                        "request_transform": {"file": request_transform},
                        "response_transform": {"file": response_transform},
                        "retry": {
                            "max_attempts": 3,
                            "backoff_ms": 1000,
                            "dlq_topic": f"{target_id}.request.v1.dlq",
                        },
                        "timeout_ms": 30000,
                    }
                    for (
                        target_id,
                        request_schema,
                        response_schema,
                        request_transform,
                        response_transform,
                    ) in target_specs
                ],
                "outbound_schema": {"file": "schemas/payment-router-response.json"},
                "nack_routing": {
                    "mode": "fixed",
                    "fixed_topic": "payments.router.nack.v1",
                    "default_error_topic": "payments.router.error.v1",
                },
            },
        )
    ]
    s.kafka_route_transforms = [
        KafkaRouteTransform(
            route_name="payment-router",
            router_target_transforms=[
                KafkaRouterTargetTransform(
                    target_id="d1_us_core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="paymentId", target="payment_id")
                    ],
                    response_transform_rows=[
                        KafkaRouterTransformRow(source="status", target="status")
                    ],
                ),
                KafkaRouterTargetTransform(
                    target_id="d2_eu_core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="paymentId", target="paymentIdentifier"),
                        KafkaRouterTransformRow(source="amount", target="amountValue"),
                        KafkaRouterTransformRow(source="iban", target="debtorIban"),
                    ],
                    response_transform_rows=[
                        KafkaRouterTransformRow(source="status", target="status")
                    ],
                ),
                KafkaRouterTargetTransform(
                    target_id="d3_india_core",
                    request_transform_rows=[
                        KafkaRouterTransformRow(source="paymentId", target="paymentReference")
                    ],
                    response_transform_rows=[
                        KafkaRouterTransformRow(source="status", target="status")
                    ],
                ),
            ],
        )
    ]
    return s


def test_kafka_router_multi_target_export_preserves_preseeded_target_request_schemas():
    s = _multi_target_router_session()

    schema_contents = {
        "schemas/d1-us-payment-request.json": '{"type":"object","properties":{"payment_id":{"type":"string"},"from_account":{"type":"string"}}}',
        "schemas/d2-eu-payment-request.json": '{"type":"object","properties":{"paymentIdentifier":{"type":"string"},"amountValue":{"type":"number"},"debtorIban":{"type":"string"}}}',
        "schemas/d3-india-payment-request.json": '{"type":"object","properties":{"paymentReference":{"type":"string"},"ifscCode":{"type":"string"}}}',
        "schemas/d1-us-payment-response.json": '{"type":"object","properties":{"status":{"type":"string"}}}',
        "schemas/d2-eu-payment-response.json": '{"type":"object","properties":{"status":{"type":"string"}}}',
        "schemas/d3-india-payment-response.json": '{"type":"object","properties":{"status":{"type":"string"}}}',
        "schemas/payment-router-response.json": '{"type":"object","properties":{"status":{"type":"string"}}}',
    }

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "payments"
        for rel, content in schema_contents.items():
            path = project_dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")

        written = write_package(s, root)

        for rel, expected_content in schema_contents.items():
            assert (project_dir / rel).read_text(encoding="utf-8") == expected_content
            assert rel in written

        generic_doc = yaml.safe_load(s.kafka_topic_pairs[0].downstream_schema_content)
        d2_doc = yaml.safe_load(
            (project_dir / "schemas/d2-eu-payment-request.json").read_text(encoding="utf-8")
        )
        assert "payment_id" in generic_doc["properties"]
        assert "paymentIdentifier" in d2_doc["properties"]
        assert "payment_id" not in d2_doc["properties"]
        assert "transforms/d2-eu-request.yaml" in written
        assert "schemas/payment-router-downstream.json" not in written


def test_kafka_router_multi_target_export_requires_missing_target_schemas():
    s = _multi_target_router_session()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        project_dir = root / "payments"
        (project_dir / "schemas").mkdir(parents=True)
        (project_dir / "schemas/payment-router-response.json").write_text(
            '{"type":"object","properties":{"status":{"type":"string"}}}',
            encoding="utf-8",
        )
        for rel in (
            "schemas/d1-us-payment-response.json",
            "schemas/d2-eu-payment-response.json",
            "schemas/d3-india-payment-response.json",
        ):
            (project_dir / rel).write_text(
                '{"type":"object","properties":{"status":{"type":"string"}}}',
                encoding="utf-8",
            )

        with pytest.raises(PackageWriteError) as exc:
            write_package(s, root)

        message = str(exc.value)
        assert "schemas/d1-us-payment-request.json" in message
        assert "schemas/d2-eu-payment-request.json" in message
        assert "schemas/d3-india-payment-request.json" in message
        assert not (project_dir / "schemas/d1-us-payment-request.json").exists()
        assert not (project_dir / "schemas/d2-eu-payment-request.json").exists()
        assert not (project_dir / "schemas/d3-india-payment-request.json").exists()


def test_empty_rule_entries_do_not_create_broken_manifest_paths():
    s = _full_session()
    s.entity_rules.append(
        EntityRules(
            entity_name="TransactionHistory",
            rules=[],
            file_path="rules/transactionhistory-business-rules.yaml",
        )
    )

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"
        manifest = yaml.safe_load((project_dir / "app-definition.yaml").read_text())

        assert manifest["rules"] == ["rules/account-business-rules.yaml"]
        assert not (project_dir / "rules/transactionhistory-business-rules.yaml").exists()


def test_legacy_notes_written():
    s = _full_session()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        write_package(s, root)
        project_dir = root / "records"
        notes = (project_dir / "legacy/records-notes.md").read_text()
        assert "Synthetic compatibility note" in notes


# ---------------------------------------------------------------------------
# P1 (fifth-pass): Re-ingesting a different source refreshes existing interfaces
# ---------------------------------------------------------------------------

def test_source_switch_file_to_url_refreshes_existing_interface():
    """Switching from file to URL after an interface already exists must update
    spec_url and clear spec/spec_content on the reused interface.

    Repro: user uploads file (spec=upstream/old.yaml, spec_content="..."),
    goes back, switches to URL mode, re-saves Step 3.  The existing interface
    must now carry spec_url and have spec=None/spec_content=None so the exported
    manifest uses the new URL source instead of the stale file path.
    """
    from app.models.project import ProjectSession
    from app.routes.entities import _apply_spec_source

    # Existing interface built when source was a local file
    iface = UpstreamInterface(
        name="dda-customer-api",
        type="rest-json",
        entity_name="Customer",
        spec="upstream/old.yaml",
        spec_content="openapi: '3.0.0'\ninfo:\n  title: Old",
        spec_url=None,
    )

    # Session now reflects URL mode (user switched source)
    session = ProjectSession()
    session.raw_spec_url = "https://new.example.com/swagger.json"
    session.raw_spec_filename = None
    session.raw_spec_content = None

    _apply_spec_source(iface, session)

    assert iface.spec_url == "https://new.example.com/swagger.json"
    assert iface.spec is None, "spec must be cleared when switching to URL mode"
    assert iface.spec_content is None, "spec_content must be cleared when switching to URL mode"


def test_source_switch_url_to_file_refreshes_existing_interface():
    """Switching from URL to file after an interface already exists must update
    spec/spec_content and clear spec_url on the reused interface.
    """
    from app.models.project import ProjectSession
    from app.routes.entities import _apply_spec_source

    iface = UpstreamInterface(
        name="dda-customer-api",
        type="rest-json",
        entity_name="Customer",
        spec=None,
        spec_content=None,
        spec_url="https://old.example.com/swagger.json",
    )

    session = ProjectSession()
    session.raw_spec_url = None
    session.raw_spec_filename = "customer-api.yaml"
    session.raw_spec_content = "openapi: '3.0.0'\ninfo:\n  title: Customer"

    _apply_spec_source(iface, session)

    assert iface.spec == "upstream/customer-api.yaml"
    assert iface.spec_content == "openapi: '3.0.0'\ninfo:\n  title: Customer"
    assert iface.spec_url is None, "spec_url must be cleared when switching to file mode"


def test_unchanged_embedded_source_keeps_writer_derived_spec_path_unset():
    """A reopened project must not pin the writer's current default path on Step 3 save."""
    from app.models.project import ProjectSession
    from app.routes.entities import _apply_spec_source

    content = "openapi: '3.0.0'\ninfo:\n  title: Customer"
    iface = UpstreamInterface(
        name="dda-customer-api",
        type="rest-json",
        entity_name="Customer",
        spec=None,
        spec_content=content,
        spec_url=None,
    )
    session = ProjectSession(
        raw_spec_filename="customer-api.yaml",
        raw_spec_content=content,
    )

    _apply_spec_source(iface, session)

    assert iface.spec is None
    assert iface.spec_content == content
    assert iface.spec_url is None


def test_same_content_new_filename_refreshes_existing_explicit_spec_path():
    """An explicit path follows the current file source even when bytes are unchanged."""
    from app.models.project import ProjectSession
    from app.routes.entities import _apply_spec_source

    content = "openapi: '3.0.0'\ninfo:\n  title: Customer"
    iface = UpstreamInterface(
        name="dda-customer-api",
        type="rest-json",
        entity_name="Customer",
        spec="upstream/old.yaml",
        spec_content=content,
        spec_url=None,
    )
    session = ProjectSession(
        raw_spec_filename="renamed.yaml",
        raw_spec_content=content,
    )

    _apply_spec_source(iface, session)

    assert iface.spec == "upstream/renamed.yaml"
    assert iface.spec_content == content
    assert iface.spec_url is None


def test_source_switch_to_manual_clears_all_spec_fields():
    """Switching to manual mode must clear spec, spec_url and spec_content
    so no stale file or URL reference survives on the interface.
    """
    from app.models.project import ProjectSession
    from app.routes.entities import _apply_spec_source

    iface = UpstreamInterface(
        name="dda-customer-api",
        type="rest-json",
        entity_name="Customer",
        spec="upstream/old.yaml",
        spec_content="openapi: '3.0.0'",
        spec_url=None,
    )

    # Manual mode — all session source fields are None
    session = ProjectSession()
    session.raw_spec_url = None
    session.raw_spec_filename = None
    session.raw_spec_content = None

    _apply_spec_source(iface, session)

    assert iface.spec is None
    assert iface.spec_url is None
    assert iface.spec_content is None
