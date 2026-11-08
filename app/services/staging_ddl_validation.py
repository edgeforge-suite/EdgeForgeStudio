"""Validation helpers and DDL generator for staging-table authoring."""

from __future__ import annotations

import re

_CREATE_TABLE_RE = re.compile(r"create\s+table\b", re.IGNORECASE)
_CREATE_TABLE_IDENTIFIER_RE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?"
    r"(?P<identifier>"
    r'(?:(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)\s*\.\s*)*'
    r'(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[A-Za-z_][\w$]*)'
    r")",
    re.IGNORECASE,
)
_COLUMN_VARCHAR_RE = re.compile(
    r'^\s*(?:"(?P<dq>[^"]+)"|`(?P<bq>[^`]+)`|\[(?P<br>[^\]]+)\]|(?P<plain>[A-Za-z_][\w$]*))\s+varchar\s*\(\s*(?P<width>\d+)\s*\)',
    re.IGNORECASE,
)
_NON_COLUMN_PREFIXES = (
    "primary key",
    "foreign key",
    "constraint ",
    "unique ",
    "check ",
    "index ",
    "key ",
)


# Types that take a single length argument.
_LENGTH_TYPES = {"VARCHAR", "CHAR", "NVARCHAR", "NCHAR"}
# Types that take precision[, scale].
_PRECISION_TYPES = {"DECIMAL", "NUMERIC", "NUMBER"}
# Types with no parameters.
_BARE_TYPES = {
    "INT", "INTEGER", "BIGINT", "SMALLINT", "TINYINT",
    "FLOAT", "DOUBLE", "REAL",
    "DATE", "DATETIME", "TIMESTAMP", "TIME",
    "BOOLEAN", "BOOL",
    "TEXT", "CLOB", "LONGTEXT", "MEDIUMTEXT",
    "BLOB",
    "JSON",
}


def generate_ddl_from_columns(
    table_name: str,
    columns: list[dict],
) -> str:
    """Generate a CREATE TABLE statement from structured column definitions.

    Each column dict may contain:
      name       (str, required)
      type       (str, required — one of the supported type names above)
      length     (int, used for VARCHAR/CHAR etc.)
      precision  (int, used for DECIMAL/NUMERIC)
      scale      (int, optional scale for DECIMAL/NUMERIC)
      nullable   (bool, default True; False → NOT NULL)

    The output matches Studio's staging-table export format. The caller must pass
    a sanitised table_name.
    """
    if not table_name or not table_name.strip():
        raise ValueError("table_name must not be empty")
    if not columns:
        raise ValueError("at least one column is required")

    col_lines: list[str] = []
    for col in columns:
        col_name = (col.get("name") or "").strip()
        col_type = (col.get("type") or "VARCHAR").strip().upper()
        if not col_name:
            continue
        nullable = col.get("nullable", True)

        if col_type in _LENGTH_TYPES:
            length = col.get("length")
            if length is None:
                length = 255
            type_str = f"{col_type}({int(length)})"
        elif col_type in _PRECISION_TYPES:
            # Accept either "precision" or "length" as the precision argument so
            # the JS column builder (which uses a single "length" input for both
            # VARCHAR lengths and DECIMAL precisions) round-trips correctly.
            precision = col.get("precision") or col.get("length")
            if precision is None:
                precision = 18
            scale = col.get("scale")
            if scale is not None:
                type_str = f"{col_type}({int(precision)},{int(scale)})"
            else:
                type_str = f"{col_type}({int(precision)})"
        else:
            type_str = col_type

        null_clause = "" if nullable else " NOT NULL"
        col_lines.append(f"  {col_name} {type_str}{null_clause}")

    if not col_lines:
        raise ValueError("no valid columns provided")

    body = ",\n".join(col_lines)
    return f"CREATE TABLE {table_name.strip()} (\n{body}\n);"


def extract_table_name_from_create_ddl(ddl: str) -> str | None:
    """Return the first CREATE TABLE name from lightweight staging DDL."""
    identifier = extract_table_identifier_from_create_ddl(ddl)
    return identifier["name"] if identifier else None


def extract_table_identifier_from_create_ddl(ddl: str) -> dict | None:
    """Return parsed CREATE TABLE identifier metadata.

    ``name`` is always the actual table segment, so ``CREATE TABLE dbo.customer``
    returns ``customer``. ``qualified_name`` preserves the unquoted qualified
    path for display/validation, and ``quoted`` marks whether the table segment
    used a quoted identifier that should be compared case-sensitively.
    """
    match = _CREATE_TABLE_IDENTIFIER_RE.search(ddl or "")
    if not match:
        return None
    parts = _split_qualified_identifier(match.group("identifier"))
    if not parts:
        return None
    return {
        "name": parts[-1]["name"],
        "qualified_name": ".".join(part["name"] for part in parts),
        "quoted": bool(parts[-1]["quoted"]),
    }


def table_name_matches_create_identifier(visible_table_name: str, identifier: dict | None) -> bool:
    """Return whether a visible table name matches a parsed CREATE TABLE name."""
    if not identifier:
        return True
    visible = (visible_table_name or "").strip()
    if not visible:
        return True
    candidates = {identifier["name"], identifier["qualified_name"]}
    if identifier.get("quoted"):
        return visible in candidates
    normalized_visible = _normalize_unquoted_identifier(visible)
    return normalized_visible in {
        _normalize_unquoted_identifier(candidate)
        for candidate in candidates
    }


def parse_columns_from_create_ddl(ddl: str) -> dict | None:
    """Parse a simple CREATE TABLE statement into Studio column-builder rows.

    This parser is intentionally lightweight and exists only to restore the
    authoring aid in Step 4. It preserves the original DDL separately and does
    not attempt to normalize or rewrite manual SQL.
    """
    table_name = extract_table_name_from_create_ddl(ddl)
    blocks = _extract_create_table_blocks(ddl or "")
    if not table_name or not blocks:
        return None

    columns: list[dict] = []
    for part in _split_top_level_columns(blocks[0]):
        low = part.strip().lower()
        if not low or low.startswith(_NON_COLUMN_PREFIXES):
            continue
        parsed = _parse_column_definition(part)
        if parsed is None:
            continue
        columns.append(parsed)

    return {"table_name": table_name, "columns": columns} if columns else None


# Matches the column name at the start of a column definition line.
_COLUMN_NAME_RE = re.compile(
    r'^\s*(?:"(?P<dq>[^"]+)"|`(?P<bq>[^`]+)`|\[(?P<br>[^\]]+)\]|(?P<plain>[A-Za-z_][\w$]*))\s+\w',
)


def extract_column_names_from_ddl(ddl: str) -> set[str] | None:
    """Return the column names extracted from the first CREATE TABLE block.

    Returns ``None`` when no CREATE TABLE is found, the body cannot be located,
    or no column definitions can be confidently extracted.  Callers must treat
    ``None`` as "unparseable / uncertain" and degrade to a non-blocking warning
    rather than a hard error, to avoid false positives on complex hand-authored
    SQL that the lightweight parser cannot handle.
    """
    blocks = _extract_create_table_blocks(ddl or "")
    if not blocks:
        return None

    parts = _split_top_level_columns(blocks[0])
    if not parts:
        return None

    column_names: set[str] = set()
    for part in parts:
        low = part.strip().lower()
        if not low or low.startswith(_NON_COLUMN_PREFIXES):
            continue
        m = _COLUMN_NAME_RE.match(part)
        if not m:
            # Unrecognised non-constraint part — cannot prove we understood the
            # full column set.  Degrade to None so callers fall back to a
            # non-blocking warning rather than hard-blocking on a partial set.
            return None
        name = m.group("dq") or m.group("bq") or m.group("br") or m.group("plain")
        if name:
            column_names.add(name)

    return column_names if column_names else None


def validate_staging_ddl(ddl_text: str) -> list[dict[str, str]]:
    """Return non-blocking warnings for suspicious staging DDL patterns."""
    warnings: list[dict[str, str]] = []

    for block in _extract_create_table_blocks(ddl_text or ""):
        for column_def in _split_top_level_columns(block):
            warning = _column_warning(column_def)
            if warning is not None:
                warnings.append(warning)

    return warnings


def _parse_column_definition(column_def: str) -> dict | None:
    match = re.match(
        r'^\s*(?:"(?P<dq>[^"]+)"|`(?P<bq>[^`]+)`|\[(?P<br>[^\]]+)\]|(?P<plain>[A-Za-z_][\w$]*))'
        r"\s+(?P<type>[A-Za-z][A-Za-z0-9_]*)"
        r"\s*(?:\(\s*(?P<arg1>\d+)(?:\s*,\s*(?P<arg2>\d+))?\s*\))?",
        column_def,
        re.IGNORECASE,
    )
    if not match:
        return None

    raw_type = match.group("type").upper()
    display_type = {
        "VARCHAR2": "VARCHAR",
        "NUMBER": "DECIMAL",
    }.get(raw_type, raw_type)
    if display_type not in _LENGTH_TYPES and display_type not in _PRECISION_TYPES and display_type not in _BARE_TYPES:
        return None

    column: dict = {
        "name": match.group("dq") or match.group("bq") or match.group("br") or match.group("plain"),
        "type": display_type,
        "nullable": not bool(re.search(r"\bNOT\s+NULL\b", column_def, re.IGNORECASE)),
    }
    arg1 = match.group("arg1")
    arg2 = match.group("arg2")
    if display_type in _LENGTH_TYPES and arg1:
        column["length"] = int(arg1)
    elif display_type in _PRECISION_TYPES and arg1:
        column["length"] = int(arg1)
        if arg2 is not None:
            column["scale"] = int(arg2)
    return column


def _split_qualified_identifier(identifier: str) -> list[dict]:
    parts: list[dict] = []
    pos = 0
    length = len(identifier or "")
    while pos < length:
        while pos < length and identifier[pos].isspace():
            pos += 1
        if pos >= length:
            break

        quoted = False
        if identifier[pos] == '"':
            end = identifier.find('"', pos + 1)
            if end == -1:
                return []
            name = identifier[pos + 1:end]
            quoted = True
            pos = end + 1
        elif identifier[pos] == "`":
            end = identifier.find("`", pos + 1)
            if end == -1:
                return []
            name = identifier[pos + 1:end]
            quoted = True
            pos = end + 1
        elif identifier[pos] == "[":
            end = identifier.find("]", pos + 1)
            if end == -1:
                return []
            name = identifier[pos + 1:end]
            quoted = True
            pos = end + 1
        else:
            match = re.match(r"[A-Za-z_][\w$]*", identifier[pos:])
            if not match:
                return []
            name = match.group(0)
            pos += len(name)

        parts.append({"name": name, "quoted": quoted})
        while pos < length and identifier[pos].isspace():
            pos += 1
        if pos < length:
            if identifier[pos] != ".":
                return []
            pos += 1

    return parts


def _normalize_unquoted_identifier(identifier: str) -> str:
    return re.sub(r"\s+", "", identifier or "").lower()


def _extract_create_table_blocks(ddl_text: str) -> list[str]:
    blocks: list[str] = []

    for match in _CREATE_TABLE_RE.finditer(ddl_text):
        open_paren = ddl_text.find("(", match.end())
        if open_paren == -1:
            continue

        depth = 0
        for idx in range(open_paren, len(ddl_text)):
            ch = ddl_text[idx]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(ddl_text[open_paren + 1:idx])
                    break

    return blocks


def _split_top_level_columns(block: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    depth = 0

    for ch in block:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(ch)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)

    return parts


def _column_warning(column_def: str) -> dict[str, str] | None:
    lowered = column_def.strip().lower()
    if not lowered or lowered.startswith(_NON_COLUMN_PREFIXES):
        return None

    match = _COLUMN_VARCHAR_RE.match(column_def)
    if not match:
        return None

    column_name = (
        match.group("dq")
        or match.group("bq")
        or match.group("br")
        or match.group("plain")
        or ""
    )
    width = int(match.group("width"))

    if column_name.lower().endswith("_id") and width < 36:
        return {
            "column": column_name,
            "message": (
                f"{column_name} is VARCHAR({width}) — UUID values need "
                "VARCHAR(36). Consider widening."
            ),
        }

    return None
