"""Read-only status and CSV export for Studio's durable audit database."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from app.services.settings import StudioSettings, StudioSettingsError, get_studio_settings

AUDIT_COLUMNS = (
    "id",
    "event_type",
    "principal_id",
    "session_id",
    "project_id",
    "outcome",
    "timestamp",
    "recorded_at",
)

_SQLITE_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")


def _read_only_connection(db_path: Path) -> sqlite3.Connection:
    uri = f"{db_path.expanduser().resolve(strict=False).as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=2)
    conn.row_factory = sqlite3.Row
    return conn


def _paths_refer_to_same_existing_file(first: Path, second: Path) -> bool:
    try:
        return first.exists() and second.exists() and os.path.samefile(first, second)
    except OSError:
        return False


def _validate_export_destination(*, db_path: Path, out_path: Path) -> None:
    resolved_db = db_path.expanduser().resolve(strict=False)
    resolved_output = out_path.expanduser().resolve(strict=False)
    protected_paths = (resolved_db,) + tuple(
        Path(f"{resolved_db}{suffix}") for suffix in _SQLITE_SIDECAR_SUFFIXES
    )
    for protected_path in protected_paths:
        if resolved_output == protected_path or _paths_refer_to_same_existing_file(
            out_path, protected_path
        ):
            raise ValueError(
                "--out must not refer to the audit database or its SQLite sidecar files."
            )


def _formula_safe_csv_cell(value: object) -> object:
    if not isinstance(value, str):
        return value
    trigger_index = 0
    while trigger_index < len(value):
        char = value[trigger_index]
        if not char.isspace() and unicodedata.category(char) not in {"Cc", "Cf"}:
            break
        trigger_index += 1
    if trigger_index < len(value) and value[trigger_index] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return value


def audit_database_status(settings: StudioSettings) -> dict[str, object]:
    status: dict[str, object] = {
        "mode": settings.audit_sink,
        "db_path": str(settings.audit_db_path),
        "db_reachable": False,
        "row_count": None,
        "oldest_recorded_at": None,
        "newest_recorded_at": None,
    }
    conn: sqlite3.Connection | None = None
    try:
        conn = _read_only_connection(settings.audit_db_path)
        conn.execute("SELECT 1").fetchone()
        row = conn.execute(
            """
            SELECT COUNT(*) AS row_count,
                   MIN(recorded_at) AS oldest_recorded_at,
                   MAX(recorded_at) AS newest_recorded_at
            FROM audit_events
            """
        ).fetchone()
        status.update(
            {
                "db_reachable": True,
                "row_count": int(row["row_count"]),
                "oldest_recorded_at": row["oldest_recorded_at"],
                "newest_recorded_at": row["newest_recorded_at"],
            }
        )
    except (OSError, sqlite3.Error):
        pass
    finally:
        if conn is not None:
            conn.close()
    return status


def export_audit_csv(
    settings: StudioSettings,
    *,
    since: str,
    out_path: Path,
) -> int:
    since_utc = _normalize_since(since)
    _validate_export_destination(db_path=settings.audit_db_path, out_path=out_path)
    conn = _read_only_connection(settings.audit_db_path)
    try:
        cursor = conn.execute(
            """
            SELECT id, event_type, principal_id, session_id, project_id,
                   outcome, timestamp, recorded_at
            FROM audit_events
            WHERE recorded_at >= ?
            ORDER BY recorded_at, id
            """,
            (since_utc,),
        )
        with out_path.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=AUDIT_COLUMNS)
            writer.writeheader()
            count = 0
            for row in cursor:
                writer.writerow(
                    {
                        column: _formula_safe_csv_cell(row[column])
                        for column in AUDIT_COLUMNS
                    }
                )
                count += 1
            return count
    finally:
        conn.close()


def _normalize_since(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("--since must be a valid ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--status", action="store_true")
    action.add_argument("--since")
    parser.add_argument("--out", type=Path)
    return parser


def main(argv: list[str] | None = None, *, stdout: TextIO | None = None) -> int:
    output = stdout or sys.stdout
    args = _parser().parse_args(argv)
    try:
        settings = get_studio_settings()
    except StudioSettingsError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.status:
        if args.out is not None:
            print("--out is only valid with --since.", file=sys.stderr)
            return 2
        status = audit_database_status(settings)
        print(json.dumps(status), file=output)
        return 0 if status["db_reachable"] else 1

    if args.out is None:
        print("--out is required with --since.", file=sys.stderr)
        return 2
    try:
        count = export_audit_csv(settings, since=args.since, out_path=args.out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, sqlite3.Error):
        print("Audit database is unavailable.", file=sys.stderr)
        return 1
    print(f"Exported {count} audit event(s).", file=output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
