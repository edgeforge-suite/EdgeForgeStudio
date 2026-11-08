from __future__ import annotations

import pytest

from app.services.csv_layout import (
    CsvLayoutError,
    materialize_csv_layout,
    prepare_csv_layout_for_export,
    project_csv_layout,
    validate_csv_layout_content,
)

CURRENT_CSV = """# EOD extract, owned by Payments team
name: payments-eod
format: csv
delimiter: "|" # pipe per downstream agreement
quote_char: '"'
escape_char: '\\'
line_separator: "\\n"
encoding: UTF-8
has_header_row: true
unknown_setting: keep-me
record_types:
  data:
    indicator:
      column: 1
      value: D
    fields:
      - name: txn_id # 36 for UUID
        column: 2
        type: string
        format: uuid
      - name: amount
        column: 3
        type: decimal
        decimal_format: "0.00"
        type_coercion: decimal
  trailer:
    indicator:
      column: 1
      value: T
    fields:
      - name: record_count
        column: 2
        type: integer
        value_source: record_count
"""


def test_current_csv_projection_and_semantic_noop_are_byte_identical():
    projection = project_csv_layout(CURRENT_CSV)

    assert projection.errors == []
    assert projection.delimiter == "|"
    assert projection.has_header_row is True
    assert [field["name"] for field in projection.fields] == ["txn_id", "amount"]

    rendered = materialize_csv_layout(
        CURRENT_CSV,
        name="payments-eod",
        fields=projection.fields,
        delimiter=projection.delimiter,
        has_header_row=projection.has_header_row,
        expected_source_hash=projection.source_hash,
    )

    assert rendered == CURRENT_CSV


def test_structured_edit_preserves_comments_unknown_keys_and_advanced_metadata():
    projection = project_csv_layout(CURRENT_CSV)
    fields = [dict(field) for field in projection.fields]
    fields[0]["name"] = "transaction_id"

    rendered = materialize_csv_layout(
        CURRENT_CSV,
        name="payments-eod",
        fields=fields,
        delimiter="~",
        has_header_row=False,
        expected_source_hash=projection.source_hash,
    )

    assert "# EOD extract, owned by Payments team" in rendered
    assert "# pipe per downstream agreement" in rendered
    assert "# 36 for UUID" in rendered
    assert "unknown_setting: keep-me" in rendered
    assert "quote_char: '\"'" in rendered
    assert "escape_char: '\\'" in rendered
    assert 'line_separator: "\\n"' in rendered
    assert "format: uuid" in rendered
    assert 'decimal_format: "0.00"' in rendered
    assert "type_coercion: decimal" in rendered
    assert "value_source: record_count" in rendered
    assert "name: transaction_id" in rendered
    assert 'delimiter: "~"' in rendered
    assert "has_header_row: false" in rendered
    assert validate_csv_layout_content(rendered) == []


def test_legacy_flat_csv_upgrades_by_row_order():
    legacy = """# legacy layout
name: old-csv
format: csv
delimiter: ','
fields:
  - name: first
    column: 9
  - name: second
"""

    rendered = prepare_csv_layout_for_export(legacy, name="old-csv")

    assert "# legacy layout" in rendered
    assert "record_types:" in rendered
    assert "fields:" not in rendered.split("record_types:", 1)[0]
    projection = project_csv_layout(rendered)
    assert [field["column"] for field in projection.fields] == [1, 2]
    assert validate_csv_layout_content(rendered) == []


def test_legacy_csv_controls_upgrade_to_engine_current_keys():
    legacy_controls = """format: csv
separator: tab
header: "true"
record_types:
  data:
    fields:
      - {name: account_id, column: 1}
"""

    rendered = prepare_csv_layout_for_export(legacy_controls, name="legacy-controls")

    assert "separator:" not in rendered
    assert "header:" not in rendered
    assert 'delimiter: "\\t"' in rendered
    assert "has_header_row: true" in rendered
    assert validate_csv_layout_content(rendered) == []


def test_invalid_csv_control_values_block_instead_of_defaulting():
    invalid = """format: csv
delimiter: double-pipe
record_types:
  data:
    fields:
      - {name: account_id, column: 1}
"""

    projection = project_csv_layout(invalid)
    assert projection.errors == ["CSV delimiter must be one character, or use tab."]
    try:
        prepare_csv_layout_for_export(invalid, name="invalid-controls")
    except CsvLayoutError as exc:
        assert "delimiter" in str(exc)
    else:
        raise AssertionError("invalid CSV controls should block export")


def test_quoted_current_schema_columns_are_not_coerced_to_engine_integers():
    invalid = """format: csv
record_types:
  data:
    fields:
      - {name: account_id, column: "1"}
"""

    projection = project_csv_layout(invalid)

    assert any("positive integer column" in error for error in projection.errors)
    assert any(
        "positive integer column" in error
        for error in validate_csv_layout_content(invalid)
    )
    with pytest.raises(CsvLayoutError, match="positive integer column"):
        prepare_csv_layout_for_export(invalid, name="quoted-column")


@pytest.mark.parametrize(
    ("field_yaml", "expected_error"),
    [
        ("      - name: account_id\n", "positive integer column"),
        (
            "      - {name: account_id, column: 1, type: currency}\n",
            "unsupported type",
        ),
        ("      - broken\n", "must be a mapping"),
    ],
)
def test_invalid_current_schema_rows_block_projection_and_materialization(
    field_yaml: str,
    expected_error: str,
):
    invalid = "format: csv\nrecord_types:\n  data:\n    fields:\n" + field_yaml
    projection = project_csv_layout(invalid)

    assert any(expected_error in error for error in projection.errors)
    with pytest.raises(CsvLayoutError):
        materialize_csv_layout(
            invalid,
            name="invalid-current",
            fields=projection.fields,
            delimiter=projection.delimiter,
            has_header_row=projection.has_header_row,
            expected_source_hash=projection.source_hash,
        )


def test_null_encoding_uses_engine_default_without_rewriting_source():
    content = """format: csv
encoding: null
record_types:
  data:
    fields:
      - {name: account_id, column: 1}
"""

    assert validate_csv_layout_content(content) == []
    assert prepare_csv_layout_for_export(content, name="nullable-encoding") == content


def test_materializer_rejects_stale_source_hash():
    projection = project_csv_layout(CURRENT_CSV)

    try:
        materialize_csv_layout(
            CURRENT_CSV + "# changed\n",
            name="payments-eod",
            fields=projection.fields,
            delimiter=projection.delimiter,
            has_header_row=projection.has_header_row,
            expected_source_hash=projection.source_hash,
        )
    except CsvLayoutError as exc:
        assert "Inspect layout/sample again" in str(exc)
    else:
        raise AssertionError("stale visual projection should be rejected")


def test_malformed_and_empty_current_csv_are_invalid():
    assert "Malformed" in validate_csv_layout_content("record_types: [")[0]
    errors = validate_csv_layout_content("format: csv\nrecord_types:\n  data:\n    fields: []\n")
    assert "non-empty fields" in " ".join(errors)


def test_multiple_record_types_require_one_shared_indicator_column():
    content = """format: csv
record_types:
  data:
    indicator: {column: 1, value: D}
    fields:
      - {name: account_id, column: 2}
  trailer:
    indicator: {column: 2, value: T}
    fields:
      - {name: record_count, column: 1}
"""

    assert "one shared indicator column" in " ".join(validate_csv_layout_content(content))
