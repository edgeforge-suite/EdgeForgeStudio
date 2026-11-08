"""Tests for deterministic file contract layout/sample inspection."""

import time

from app.services.edge_contract_file_inspector import inspect_file_contract_layout


def test_fixed_width_layout_inspection_extracts_fields_and_sample_preview():
    result = inspect_file_contract_layout(
        "file-fixed-width",
        """
format: fixed-width
record_types:
  data:
    fields:
      - name: account_id
        position: 1
        length: 36
        type: string
        required: true
      - name: status
        position: 37
        length: 6
        type: string
""",
        "123456789012345678901234567890123456ACTIVE",
    )

    assert result["ok"] is True
    assert result["layout"]["fields"][0] == {
        "name": "account_id",
        "start": 1,
        "length": 36,
        "type": "string",
        "required": True,
    }
    assert result["layout"]["fields"][1]["start"] == 37
    assert result["sample_preview"]["rows"][0]["values"] == [
        {"field": "account_id", "value": "123456789012345678901234567890123456"},
        {"field": "status", "value": "ACTIVE"},
    ]


def test_fixed_width_record_type_indicator_offsets_inferred_data_fields():
    result = inspect_file_contract_layout(
        "file-fixed-width",
        """
format: fixed-width
record_types:
  data:
    indicator:
      position: 1
      length: 1
      value: D
    fields:
      - name: account_id
        length: 36
      - name: status
        length: 6
""",
        "D123456789012345678901234567890123456ACTIVE",
    )

    assert result["ok"] is True
    assert result["layout"]["indicator"] == {"position": 1, "length": 1, "value": "D"}
    assert not any("gap before field" in warning for warning in result["warnings"])
    assert result["layout"]["fields"][0]["start"] == 2
    assert result["layout"]["fields"][1]["start"] == 38
    assert result["sample_preview"]["rows"][0]["values"] == [
        {"field": "account_id", "value": "123456789012345678901234567890123456"},
        {"field": "status", "value": "ACTIVE"},
    ]


def test_fixed_width_sample_preview_preserves_meaningful_padding():
    result = inspect_file_contract_layout(
        "file-fixed-width",
        """
format: fixed-width
record_types:
  data:
    fields:
      - name: padded_name
        position: 1
        length: 6
      - name: status
        position: 7
        length: 6
""",
        "  AB  ACTIVE  ",
    )

    assert result["ok"] is True
    assert result["sample_preview"]["rows"][0]["line"] == "  AB  ACTIVE  "
    assert result["sample_preview"]["rows"][0]["values"] == [
        {"field": "padded_name", "value": "  AB  "},
        {"field": "status", "value": "ACTIVE"},
    ]


def test_fixed_width_layout_inspection_warns_for_overlap_and_short_id():
    result = inspect_file_contract_layout(
        "file-fixed-width",
        """
format: fixed-width
record_types:
  data:
    fields:
      - name: account_id
        position: 1
        length: 12
      - name: status
        position: 8
        length: 6
""",
        "",
    )

    assert result["ok"] is True
    assert any("UUID-style identifier" in warning for warning in result["warnings"])
    assert any("overlaps" in warning for warning in result["warnings"])


def test_fixed_width_layout_inspection_warns_for_short_sample_line():
    result = inspect_file_contract_layout(
        "file-fixed-width",
        """
format: fixed-width
record_types:
  data:
    fields:
      - name: account_id
        position: 1
        length: 36
""",
        "short",
    )

    assert result["ok"] is True
    assert any("shorter than expected" in warning for warning in result["warnings"])


def test_fixed_width_layout_inspection_reports_malformed_yaml():
    result = inspect_file_contract_layout("file-fixed-width", "fields: [", "")

    assert result["ok"] is False
    assert any("Malformed layout/spec YAML" in error for error in result["errors"])


def test_csv_layout_inspection_supports_comma_delimiter_and_sample_preview():
    result = inspect_file_contract_layout(
        "file-csv",
        """
format: csv
delimiter: ","
has_header_row: true
fields:
  - name: account_id
    column: 1
    type: string
  - name: status
    column: 2
    required: true
""",
        "account_id,status\nA123,ACTIVE",
    )

    assert result["ok"] is True
    assert result["layout"]["delimiter"] == ","
    assert result["layout"]["delimiter_label"] == "comma (,)"
    assert result["layout"]["has_header_row"] is True
    assert result["sample_preview"]["rows"][1]["columns"] == [
        {"field": "account_id", "value": "A123"},
        {"field": "status", "value": "ACTIVE"},
    ]


def test_csv_sample_preview_uses_declared_column_numbers_not_yaml_order():
    result = inspect_file_contract_layout(
        "file-csv",
        """
format: csv
delimiter: "|"
fields:
  - name: status
    column: 2
  - name: account_id
    column: 1
""",
        "A123|ACTIVE",
    )

    assert result["ok"] is True
    assert result["sample_preview"]["rows"][0]["columns"] == [
        {"field": "account_id", "value": "A123"},
        {"field": "status", "value": "ACTIVE"},
    ]


def test_csv_layout_inspection_uses_pipe_delimiter_for_sample_preview():
    result = inspect_file_contract_layout(
        "file-csv",
        """
format: csv
delimiter: "|"
fields:
  - name: account_id
  - name: status
""",
        "A123|ACTIVE",
    )

    assert result["ok"] is True
    assert result["layout"]["delimiter"] == "|"
    assert result["layout"]["delimiter_label"] == "pipe (|)"
    assert result["sample_preview"]["rows"][0]["columns"][1]["value"] == "ACTIVE"


def test_csv_layout_inspection_uses_tilde_delimiter_for_sample_preview():
    result = inspect_file_contract_layout(
        "file-csv",
        """
format: csv
delimiter: "~"
fields:
  - name: account_id
  - name: status
""",
        "A123~ACTIVE",
    )

    assert result["ok"] is True
    assert result["layout"]["delimiter"] == "~"
    assert result["layout"]["delimiter_label"] == "tilde (~)"
    assert result["sample_preview"]["rows"][0]["columns"][1]["value"] == "ACTIVE"


def test_csv_layout_inspection_supports_tab_delimiter():
    result = inspect_file_contract_layout(
        "file-csv",
        """
format: csv
delimiter: tab
fields:
  - name: account_id
  - name: status
""",
        "A123\tACTIVE",
    )

    assert result["ok"] is True
    assert result["layout"]["delimiter"] == "\t"
    assert result["layout"]["delimiter_label"] == "tab"
    assert result["sample_preview"]["rows"][0]["columns"][1]["value"] == "ACTIVE"


def test_csv_layout_inspection_warns_on_sample_column_mismatch():
    result = inspect_file_contract_layout(
        "file-csv",
        """
format: csv
delimiter: ","
fields:
  - name: account_id
  - name: status
""",
        "A123",
    )

    assert result["ok"] is True
    assert any("layout defines 2" in warning for warning in result["warnings"])


def test_csv_layout_inspection_reports_malformed_yaml():
    result = inspect_file_contract_layout("file-csv", "fields: [", "")

    assert result["ok"] is False
    assert any("Malformed layout/spec YAML" in error for error in result["errors"])


def test_fixed_width_layout_inspection_handles_yaml_anchor_alias_expansion_without_blowup():
    """YAML anchor/alias ("billion laughs" style) payload against yaml.safe_load.

    yaml.safe_load shares anchored objects by reference instead of deep-copying
    them on each alias use, and this module's field loading (`_layout_fields`)
    only ever looks at the immediate top-level `fields` list without recursing
    into nested aliased structures. So a multiplicative-looking anchor chain -
    nominally 10**6 = 1,000,000 nodes if naively flattened - collapses to a
    handful of "not a mapping" warnings almost instantly rather than causing
    exponential time or memory growth. Verified against the real code, not
    assumed.
    """
    lines = ["leaf: &leaf {name: bombed, start: 1, length: 1}"]
    previous = "leaf"
    for index in range(6):
        name = f"level{index}"
        refs = ", ".join(f"*{previous}" for _ in range(10))
        lines.append(f"{name}: &{name} [{refs}]")
        previous = name
    lines.append(f"fields: *{previous}")
    yaml_bomb = "\n".join(lines)

    start = time.monotonic()
    result = inspect_file_contract_layout("file-fixed-width", yaml_bomb, "")
    elapsed = time.monotonic() - start

    assert elapsed < 5, f"YAML anchor-bomb inspection took {elapsed:.2f}s, expected a bounded result"
    assert result["ok"] is True
    assert result["errors"] == []
    # The top-level `fields` list contains 10 shared references to `level4`
    # lists (not mappings), so each is reported as a non-mapping field
    # rather than recursively expanded.
    assert len(result["warnings"]) == 10
    assert all(
        "expected a mapping with name/start/length" in warning for warning in result["warnings"]
    )
    assert result["layout"]["fields"] == []
