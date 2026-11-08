"""Fixed-width layout contiguity is an export blocker (task #52 / PR-A follow-on).

PR-A made Studio emit explicit `position` values for visually-authored
fixed-width layouts, so the Engine now enforces contiguity-from-position-1 at
generation. Studio must therefore refuse to export a non-contiguous layout
itself, rather than presenting it as Ready and failing downstream.

`test_studio_blocking_matches_the_real_engine` is the faithfulness guarantee:
for each layout, Studio's readiness verdict must match whether the REAL Engine
validator accepts the same generated layout. It skips cleanly when no Engine
checkout is resolvable, mirroring PR-A's tests/test_file_layout_engine_contract.py.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.models.project import DownstreamInterface, FieldMapping, LayoutField, ProjectSession
from app.services.edge_contracts import (
    INCOMPLETE,
    edge_contract_readiness,
    fixed_width_layout_contiguity_errors,
)
from app.services.mapping_generator import generate_downstream_layout

# (label, layout_fields, engine_accepts). Studio must block iff the Engine
# rejects, so `engine_accepts` doubles as "Studio marks Ready".
_LAYOUTS = [
    ("contiguous", [LayoutField(name="a", start=1, length=12), LayoutField(name="b", start=13, length=10)], True),
    ("single-at-1", [LayoutField(name="a", start=1, length=8)], True),
    ("three-contiguous", [LayoutField(name="a", start=1, length=4), LayoutField(name="b", start=5, length=4), LayoutField(name="c", start=9, length=4)], True),
    ("out-of-order-but-contiguous", [LayoutField(name="b", start=13, length=10), LayoutField(name="a", start=1, length=12)], True),
    ("gap", [LayoutField(name="a", start=1, length=12), LayoutField(name="b", start=20, length=10)], False),
    ("overlap", [LayoutField(name="a", start=1, length=12), LayoutField(name="b", start=10, length=10)], False),
    ("leading-gap", [LayoutField(name="a", start=5, length=8)], False),
    ("interior-gap-of-three", [LayoutField(name="a", start=1, length=4), LayoutField(name="b", start=5, length=4), LayoutField(name="c", start=20, length=4)], False),
    # P1 cases the falsy-filter previously let through as Ready:
    ("zero-length", [LayoutField(name="a", start=1, length=0)], False),
    ("negative-length", [LayoutField(name="a", start=1, length=-5)], False),
    ("position-zero", [LayoutField(name="a", start=0, length=8)], False),
    ("duplicate-name", [LayoutField(name="a", start=1, length=6), LayoutField(name="a", start=7, length=6)], False),
    ("blank-name", [LayoutField(name="", start=1, length=8)], False),
    ("whitespace-name", [LayoutField(name="   ", start=1, length=8)], False),
    ("blank-name-among-valid", [LayoutField(name="a", start=1, length=8), LayoutField(name=" ", start=9, length=8)], False),
]


def _fixed_width_iface(fields: list[LayoutField]) -> DownstreamInterface:
    return DownstreamInterface(
        name="eod-file",
        type="file-fixed-width",
        entity_name="Txn",
        spec="downstream/eod-file-layout.yaml",
        spec_content="format: fixed-width\n",
        layout_fields=fields,
        field_mappings=[FieldMapping(source="Txn.a", target="a")],
    )


@pytest.mark.parametrize("label, fields, accepts", _LAYOUTS)
def test_readiness_blocks_invalid_fixed_width_layouts(label, fields, accepts):
    readiness = edge_contract_readiness(_fixed_width_iface(fields), direction="downstream")
    if accepts:
        assert readiness.status != INCOMPLETE, label
        assert readiness.will_export is True, label
        assert "contiguous fixed-width field positions" in readiness.required_present
    else:
        assert readiness.status == INCOMPLETE, label
        assert readiness.will_export is False, label
        # The actionable field detail must reach required_missing (the signal
        # the board / Step 7 / export gate read), not only warnings (P2).
        assert readiness.required_missing, label
        assert readiness.required_missing == fixed_width_layout_contiguity_errors(fields)


def test_helper_messages_name_the_specific_problem():
    def one(fields):
        errs = fixed_width_layout_contiguity_errors(fields)
        assert errs, fields
        return errs[0]

    assert "gap before 'b'" in one(
        [LayoutField(name="a", start=1, length=12), LayoutField(name="b", start=20, length=10)]
    )
    assert "'b' overlaps" in one(
        [LayoutField(name="a", start=1, length=12), LayoutField(name="b", start=10, length=10)]
    )
    assert "first field at position 1" in one([LayoutField(name="a", start=5, length=8)])
    assert "valid length for 'a'" in one([LayoutField(name="a", start=1, length=0)])
    assert "valid position for 'a'" in one([LayoutField(name="a", start=0, length=8)])
    assert "unique field names ('a' repeated)" in one(
        [LayoutField(name="a", start=1, length=6), LayoutField(name="a", start=7, length=6)]
    )
    assert "a non-empty name for every field" in one([LayoutField(name="  ", start=1, length=8)])
    # Reported once even when several fields are nameless.
    assert fixed_width_layout_contiguity_errors(
        [LayoutField(name="", start=1, length=8), LayoutField(name="", start=9, length=8)]
    ).count("a non-empty name for every field") == 1
    assert (
        fixed_width_layout_contiguity_errors(
            [LayoutField(name="a", start=1, length=12), LayoutField(name="b", start=13, length=10)]
        )
        == []
    )


def test_non_contiguous_layout_blocks_export_end_to_end():
    """The readiness blocker propagates to the actual export gate: a package
    with a non-contiguous downstream layout is refused."""
    from app.services.completeness_service import build_completeness_report

    session = ProjectSession(app_name="c", bounded_context="c", app_archetype="crud")
    session.downstream_interfaces = [
        _fixed_width_iface([LayoutField(name="a", start=1, length=12), LayoutField(name="b", start=20, length=10)])
    ]
    report = build_completeness_report(session)
    assert report.is_exportable() is False
    assert any("eod-file" in item.message for item in report.manual())


def _engine_repo() -> Path:
    for value in (
        os.environ.get("EDGEFORGE_ENGINE_REPO"),
        os.environ.get("EDGEFORGE_STUDIO_ENGINE_REPO"),
        str(Path(__file__).resolve().parents[2] / "EdgeForge"),
    ):
        if not value:
            continue
        candidate = Path(value).expanduser().resolve()
        if (candidate / "appbuilder" / "metadata" / "file_contracts.py").is_file():
            return candidate
    pytest.skip("Fixed-width contiguity engine-parity test requires a resolvable Engine checkout")


@pytest.mark.parametrize("label, fields, accepts", _LAYOUTS)
def test_studio_blocking_matches_the_real_engine(label, fields, accepts, tmp_path):
    """Faithfulness: Studio blocks a layout iff the real Engine rejects it."""
    engine = _engine_repo()
    studio_blocks = edge_contract_readiness(_fixed_width_iface(fields), direction="downstream").status == INCOMPLETE

    layout_path = tmp_path / "layout.yaml"
    layout_path.write_text(generate_downstream_layout(_fixed_width_iface(fields)), encoding="utf-8")
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from appbuilder.metadata.file_contracts import load_file_layout_spec\n"
        "load_file_layout_spec(Path(sys.argv[2]), contract_type='file-fixed-width')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(engine), str(layout_path)],
        capture_output=True,
        text=True,
    )
    engine_accepts = result.returncode == 0
    # The `accepts` column is our claim; assert the REAL Engine agrees with it,
    # then assert Studio blocks exactly when the Engine rejects.
    assert engine_accepts == accepts, f"{label}: engine stderr={result.stderr}"
    assert studio_blocks == (not engine_accepts), label
