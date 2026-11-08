"""Cross-repo proof that Studio layouts satisfy the real Engine contract."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.models.project import DownstreamInterface, LayoutField
from app.services.csv_layout import materialize_csv_layout, project_csv_layout
from app.services.mapping_generator import generate_downstream_layout


def _engine_repo() -> Path:
    candidates = [
        os.environ.get("EDGEFORGE_ENGINE_REPO"),
        os.environ.get("EDGEFORGE_STUDIO_ENGINE_REPO"),
        os.environ.get("EDGEFORGE_STUDIO_DEFAULT_ENGINE_REPO"),
        str(Path(__file__).resolve().parents[2] / "EdgeForge"),
    ]
    for value in candidates:
        if not value:
            continue
        candidate = Path(value).expanduser().resolve()
        if (candidate / "appbuilder" / "metadata" / "file_contracts.py").is_file():
            return candidate
    pytest.skip("Engine file-layout contract test requires a resolvable Engine checkout")


def test_engine_accepts_studio_fixed_width_record_types_layout(tmp_path: Path):
    layout_path = tmp_path / "account-fixed-layout.yaml"
    layout_path.write_text(
        generate_downstream_layout(
            DownstreamInterface(
                name="account-fixed-out",
                type="file-fixed-width",
                layout_fields=[
                    LayoutField(name="account_id", start=1, length=12),
                    LayoutField(name="status", start=13, length=10),
                ],
            )
        ),
        encoding="utf-8",
    )

    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from appbuilder.metadata.file_contracts import load_file_layout_spec\n"
        "layout = load_file_layout_spec(Path(sys.argv[2]), contract_type='file-fixed-width')\n"
        "assert layout.format == 'fixed-width'\n"
        "assert layout.is_flat_fixed_width is False\n"
        "assert [field.position for field in layout.fields] == [1, 13]\n"
        "assert [field.length for field in layout.fields] == [12, 10]\n"
    )
    subprocess.run(
        [sys.executable, "-c", script, str(_engine_repo()), str(layout_path)],
        check=True,
    )


def test_engine_accepts_studio_csv_record_types_layout(tmp_path: Path):
    source = """# reviewed CSV contract
name: account-csv-out
format: csv
delimiter: ','
has_header_row: false
encoding: null
record_types:
  data:
    fields:
      - name: account_id
        column: 1
        type: string
      - name: status
        column: 2
        type: string
"""
    projection = project_csv_layout(source)
    layout_path = tmp_path / "account-csv-layout.yaml"
    layout_path.write_text(
        materialize_csv_layout(
            source,
            name="account-csv-out",
            fields=projection.fields,
            delimiter="tab",
            has_header_row=True,
            expected_source_hash=projection.source_hash,
        ),
        encoding="utf-8",
    )

    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "from appbuilder.metadata.file_contracts import load_file_layout_spec\n"
        "layout = load_file_layout_spec(Path(sys.argv[2]), contract_type='file-csv')\n"
        "assert layout.format == 'csv'\n"
        "assert layout.delimiter == '\\t'\n"
        "assert layout.has_header_row is True\n"
        "assert layout.encoding == 'UTF-8'\n"
        "assert [field.name for field in layout.fields] == ['account_id', 'status']\n"
        "assert [field.column for field in layout.fields] == [1, 2]\n"
    )
    subprocess.run(
        [sys.executable, "-c", script, str(_engine_repo()), str(layout_path)],
        check=True,
    )
