"""Durable regeneration-preview binding helpers.

Studio stores a managed copy of the last generated package so future preview
slices can ask the Engine for an authoritative Change Plan.  This module does
not compute diffs or call the Engine; it only captures and reports binding
state when the regen-preview flag is enabled.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from app.models.project import ProjectSession

# Reuse the contract inspector's DOCTYPE/ENTITY-guarded parser rather than
# opening a second, unguarded XML parsing path (see
# tests/test_edge_contract_inspector_security.py for the XXE/expansion coverage).
from app.services.edge_contract_inspector import _parse_xml
from app.services.path_resolver import (
    PathResolutionError,
    session_export_dir,
    session_workspace_root,
)
from app.services.retention import DURABLE_SUBDIR
from app.services.settings import StudioSettings, get_studio_settings

RegenStatus = Literal["none", "manifest-only", "regenerate-ready"]
ArtifactKind = Literal["plain", "xsd", "wsdl"]


class RegenBindingError(RuntimeError):
    """Raised when a managed baseline binding would violate path safety."""


@dataclass(frozen=True)
class RegenCaptureResult:
    captured: bool
    status: RegenStatus
    generation_run_id: str | None = None
    managed_package_ref: str | None = None
    manifest_hash: str | None = None
    baseline_hash: str | None = None
    baseline_present: bool = False


def capture_generated_package(
    session: ProjectSession,
    *,
    generated_package_path: str | Path,
    manifest_path: str | Path,
    settings: StudioSettings | None = None,
) -> RegenCaptureResult:
    """Capture the generated package into the durable managed-artifacts area."""

    settings = settings or get_studio_settings()
    if not settings.regen_preview_enabled:
        return RegenCaptureResult(captured=False, status="none")

    workspace_root = session_workspace_root(session, settings)
    source_package = _resolve_under_workspace(
        workspace_root,
        Path(generated_package_path),
        "Generated package path is outside the session workspace.",
    )
    manifest = _resolve_under_workspace(
        workspace_root,
        Path(manifest_path),
        "Manifest path is outside the session workspace.",
    )
    if not source_package.is_dir():
        raise RegenBindingError("Generated package was not found for regen-preview binding.")
    if not manifest.is_file():
        raise RegenBindingError("Manifest was not found for regen-preview binding.")
    _reject_symlinks(source_package)

    prior_package_ref = session.last_generated_package_ref
    prior_run_id = session.generation_run_id
    generation_run_id = uuid.uuid4().hex
    managed_run_root = _resolve_under_workspace(
        workspace_root,
        workspace_root / DURABLE_SUBDIR / generation_run_id,
        "Managed artifact path is outside the session workspace.",
    )
    managed_package = managed_run_root / "generated-app"
    managed_run_root.mkdir(parents=True, exist_ok=False)
    try:
        shutil.copytree(source_package, managed_package, symlinks=False)
        baseline_path = managed_package / "db" / "schema-baseline.json"
        baseline_hash = _hash_file(baseline_path) if baseline_path.is_file() else None
        manifest_hash = _generation_input_hash(manifest)
        package_ref = _relative_to_workspace(workspace_root, managed_package)
        _remove_prior_managed_run(
            workspace_root,
            package_ref=prior_package_ref,
            generation_run_id=prior_run_id,
            current_run_root=managed_run_root,
        )
    except OSError as exc:
        shutil.rmtree(managed_run_root, ignore_errors=True)
        raise RegenBindingError("Generated package could not be captured for regen-preview binding.") from exc
    except RegenBindingError:
        shutil.rmtree(managed_run_root, ignore_errors=True)
        raise

    session.last_generated_package_ref = package_ref
    session.generation_run_id = generation_run_id
    session.manifest_hash = manifest_hash
    session.baseline_hash = baseline_hash

    return RegenCaptureResult(
        captured=True,
        status=regen_status(session, settings=settings),
        generation_run_id=generation_run_id,
        managed_package_ref=package_ref,
        manifest_hash=manifest_hash,
        baseline_hash=baseline_hash,
        baseline_present=baseline_hash is not None,
    )


def regen_status(
    session: ProjectSession,
    *,
    settings: StudioSettings | None = None,
) -> RegenStatus:
    """Return read-only older-project status for future preview UI slices."""

    settings = settings or get_studio_settings()
    if not settings.regen_preview_enabled:
        return "none"
    if not session.last_generated_package_ref or not session.manifest_hash:
        return "none"

    workspace_root = session_workspace_root(session, settings)
    try:
        managed_package = _resolve_under_workspace(
            workspace_root,
            workspace_root / session.last_generated_package_ref,
            "Managed package reference is outside the session workspace.",
        )
    except RegenBindingError:
        return "none"

    baseline_present = bool(session.baseline_hash) and (
        managed_package / "db" / "schema-baseline.json"
    ).is_file()
    if not baseline_present:
        return "manifest-only"

    current_manifest = _current_manifest_path(session)
    if current_manifest is None:
        return "none"
    try:
        current_manifest = _resolve_under_workspace(
            workspace_root,
            current_manifest,
            "Current manifest path is outside the session workspace.",
        )
    except RegenBindingError:
        return "none"
    if not current_manifest.is_file():
        return "none"
    try:
        current_hash = _generation_input_hash(current_manifest)
    except OSError:
        # Never let a filesystem hiccup while hashing turn a status check into
        # a 500 -- report no delta rather than raising out of the request path.
        return "none"
    return "regenerate-ready" if current_hash != session.manifest_hash else "none"


def _current_manifest_path(session: ProjectSession) -> Path | None:
    if not session.last_export_path:
        return None
    try:
        export_dir = session_export_dir(session)
    except PathResolutionError:
        # An unusable stored path means there is no readable manifest -- report
        # that rather than raising, since regen_status runs on the page render.
        return None
    return export_dir / "app-definition.yaml" if export_dir else None


def _resolve_under_workspace(workspace_root: Path, target: Path, message: str) -> Path:
    resolved_workspace = workspace_root.expanduser().resolve(strict=False)
    resolved_target = target.expanduser().resolve(strict=False)
    if resolved_target == resolved_workspace:
        return resolved_target
    try:
        resolved_target.relative_to(resolved_workspace)
    except ValueError as exc:
        raise RegenBindingError(message) from exc
    return resolved_target


def _relative_to_workspace(workspace_root: Path, target: Path) -> str:
    resolved_workspace = workspace_root.expanduser().resolve(strict=False)
    resolved_target = target.expanduser().resolve(strict=False)
    try:
        return resolved_target.relative_to(resolved_workspace).as_posix()
    except ValueError as exc:
        raise RegenBindingError("Managed package reference is outside the session workspace.") from exc


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


# XSD/WSDL transitive includes, discovered the way the Engine discovers them
# (appbuilder/contracts/xml_contracts.py, soap_contracts.py): only xs:include
# elements that are DIRECT children of an XSD document root or a schema directly
# under wsdl:types.
_XSD_NS = "http://www.w3.org/2001/XMLSchema"
_WSDL_NS = "http://schemas.xmlsoap.org/wsdl/"
_XSD_SCHEMA_TAG = f"{{{_XSD_NS}}}schema"
_XSD_INCLUDE_TAG = f"{{{_XSD_NS}}}include"
_WSDL_TYPES_TAG = f"{{{_WSDL_NS}}}types"


def _xml_include_targets(
    content: str | bytes,
    *,
    root_kind: Literal["xsd", "wsdl"],
) -> list[str]:
    """schemaLocation values of the xs:include elements the Engine would follow.

    The document is PARSED rather than text-scanned. That is what makes an
    entity-encoded location (``../shared&#32;dir/child.xsd``) decode to the real
    filename, and what keeps include-shaped text inside an XML comment from being
    followed -- a text scan gets both wrong, in opposite directions: it misses a
    real input and invents a fake one.

    Root semantics are retained from the manifest: XML/XSD contracts accept only
    an xs:schema document root, while SOAP/WSDL contracts accept only schemas
    directly under wsdl:types. Samples and documentation fragments are therefore
    never promoted into schema catalogs.

    Parsing raw bytes preserves XML-declared encodings while enforcing the same
    active DTD/entity rejection policy as Studio inspection and the Engine.
    """
    root, errors = _parse_xml(
        content,
        label="WSDL" if root_kind == "wsdl" else "XSD",
    )
    if root is None or errors:
        return []
    if root_kind == "xsd":
        schemas = [root] if root.tag == _XSD_SCHEMA_TAG else []
    else:
        schemas = root.findall(f"{_WSDL_TYPES_TAG}/{_XSD_SCHEMA_TAG}")
    targets: list[str] = []
    for schema in schemas:
        for include in schema.findall(_XSD_INCLUDE_TAG):
            location = include.attrib.get("schemaLocation")
            if location and location.strip():
                targets.append(location)
    return targets


def _manifest_artifact_roots(manifest_data: Any) -> set[tuple[str, ArtifactKind]]:
    """Engine-referenced files plus the semantics of schema entry points.

    Extraction is SCHEMA-LOCATION-aware, not key-name-aware: a value counts only
    where the Engine's typed model actually reads a path. Matching a key name at
    any depth was broader than the contract -- a router condition whose arbitrary
    value happened to be ``{file: notes.txt}`` got seeded as an Engine input even
    though referenced_paths() ignores it, inventing a regen delta. Reading the
    same positions the Engine reads keeps the closure EQUAL to the Engine's input
    set rather than merely a superset of it.

    XSD and WSDL roots retain their kind so only those files participate in
    transitive include discovery. Other direct inputs, including XML samples,
    remain hashed but are never interpreted as schema catalogs.
    """
    found: set[tuple[str, ArtifactKind]] = set()

    def add(value: Any, kind: ArtifactKind = "plain") -> None:
        if isinstance(value, str) and value.strip():
            found.add((value, kind))

    def as_map(node: Any) -> dict[str, Any]:
        return node if isinstance(node, dict) else {}

    def as_seq(node: Any) -> list[Any]:
        return node if isinstance(node, list) else []

    root = as_map(manifest_data)

    for raw_interface in [
        *as_seq(root.get("upstream_interfaces")),
        *as_seq(root.get("downstream_interfaces")),
    ]:
        interface = as_map(raw_interface)
        # The Engine takes the FIRST of these that is set (if/elif), so a spec
        # sitting alongside an xsd_path is not actually a generation input.
        for key in ("xsd_path", "wsdl_path", "spec"):
            value = interface.get(key)
            if isinstance(value, str) and value.strip():
                if key == "xsd_path":
                    kind: ArtifactKind = "xsd"
                elif key == "wsdl_path":
                    kind = "wsdl"
                elif interface.get("type") == "xml-xsd":
                    kind = "xsd"
                elif interface.get("type") == "soap-wsdl":
                    kind = "wsdl"
                else:
                    kind = "plain"
                add(value, kind)
                break
        add(interface.get("mapping"))
        add(interface.get("sample"))
        for sample in as_seq(interface.get("samples")):
            add(sample)
        for raw_operation in as_seq(interface.get("operations")):
            operation = as_map(raw_operation)
            add(operation.get("request_sample"))
            add(operation.get("response_sample"))

    for raw_handoff in as_seq(root.get("data_handoffs")):
        handoff = as_map(raw_handoff)
        add(handoff.get("spec"))
        add(handoff.get("mapping"))

    for raw_route in as_seq(root.get("async_routes")):
        route = as_map(raw_route)
        if route.get("pattern") == "router":
            config = as_map(route.get("router_config"))
            for key in ("inbound_schema", "outbound_schema"):
                add(as_map(config.get(key)).get("file"))
            for raw_target in as_seq(config.get("targets")):
                target = as_map(raw_target)
                for key in (
                    "request_schema",
                    "response_schema",
                    "request_transform",
                    "response_transform",
                ):
                    add(as_map(target.get(key)).get("file"))
            continue
        for key in ("upstream_topic", "downstream_topic"):
            topic = as_map(route.get(key))
            add(topic.get("message_schema"))
            add(topic.get("sample"))
        add(route.get("transform_mapping"))
        for key in ("upstream_reply_topic", "downstream_reply_topic"):
            add(as_map(route.get(key)).get("message_schema"))
        add(route.get("response_transform_mapping"))

    for rule in as_seq(root.get("rules")):
        add(rule)
    for reference in as_seq(root.get("legacy_references")):
        add(reference)

    return found


def _manifest_artifact_paths(manifest_data: Any) -> set[str]:
    """Files read by Engine ``ProjectDefinition.referenced_paths()``.

    This path-only compatibility view remains the parity-test surface; closure
    traversal uses the typed roots above so it can mirror Engine schema loading
    without changing which direct files are considered generation inputs.
    """
    return {path for path, _kind in _manifest_artifact_roots(manifest_data)}


def _resolve_package_local(
    value: str,
    base_dir: Path,
    package_dir: Path,
    *,
    allow_absolute: bool = False,
) -> Path | None:
    """Resolve a reference (relative to `base_dir`, the referencing file's own
    directory) to a real, package-local, non-symlink file, or None.

    Parent-relative (`../shared/child.xsd`) and spaced targets are honoured --
    what matters is that the RESOLVED path stays within the package dir. URLs,
    symlinks, directories, and anything escaping the package are rejected.

    `allow_absolute` mirrors the Engine's two different rules: a manifest path
    must be relative (`_normalize_manifest_path` rejects absolute outright),
    while an xs:include location may be absolute so long as it still resolves
    inside the package boundary (`_resolve_include_path`).
    """
    text = (value or "").strip()
    if not text or re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*:", text):
        return None
    raw = Path(text)
    if raw.is_absolute() and not allow_absolute:
        return None
    candidate = raw if raw.is_absolute() else base_dir / raw
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(package_dir)
    except (OSError, ValueError):
        return None
    try:
        if candidate.is_symlink() or resolved.is_symlink() or not resolved.is_file():
            return None
    except OSError:
        return None
    return resolved


def _generation_input_closure(manifest_path: Path) -> list[Path]:
    """Transitive closure of the files the Engine reads for generation: the
    artifacts the manifest references (structurally, by key), then the artifacts
    THOSE reference (a child XSD an ``<xs:include>`` pulls in), and so on.

    Reachability is the invariant. A referenced input is included wherever it
    lives -- including under generated-app/, which Studio does not reserve -- and
    a file nothing references (generated output, a stale artifact from a prior
    export, editor/OS noise like notes.txt or .DS_Store) is never reached, so it
    can neither hide a change nor invent one.

    Both hops mirror the Engine rather than approximating it: manifest paths come
    from the positions referenced_paths() reads, and include targets come from
    parsed xs:include elements. Parent-relative, spaced and entity-encoded
    locations all resolve; the closure is cycle-safe and bounded by package size.
    """
    package_dir = manifest_path.parent.resolve(strict=False)
    try:
        manifest_data = yaml.safe_load(manifest_path.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, yaml.YAMLError):
        return []

    visited: set[Path] = set()
    processed: set[tuple[Path, ArtifactKind]] = set()
    queue: list[tuple[Path, ArtifactKind]] = []
    for value, kind in _manifest_artifact_roots(manifest_data):
        resolved = _resolve_package_local(value, package_dir, package_dir)
        if resolved is not None:
            queue.append((resolved, kind))

    while queue:
        current, kind = queue.pop()
        reference = (current, kind)
        if reference in processed:
            continue
        processed.add(reference)
        visited.add(current)
        if kind == "plain":
            continue
        try:
            content = current.read_bytes()
        except OSError:
            continue
        for target in _xml_include_targets(content, root_kind=kind):
            resolved = _resolve_package_local(
                target, current.parent, package_dir, allow_absolute=True
            )
            if resolved is not None and (resolved, "xsd") not in processed:
                queue.append((resolved, "xsd"))
    return sorted(visited)


def _generation_input_hash(manifest_path: Path) -> str:
    """Hash of the manifest plus its transitive generation-input closure
    (_generation_input_closure). A change to the manifest OR to any artifact the
    Engine actually reads -- directly or transitively, even under an unchanged
    path -- flips the hash; a change to anything nothing references does not.
    Every read is guarded so a disappearing/unreadable file can't raise out of
    regen_status (a request-path call)."""
    package_dir = manifest_path.parent.resolve(strict=False)
    digest = hashlib.sha256()
    try:
        digest.update(manifest_path.read_bytes())
    except OSError:
        pass
    for path in _generation_input_closure(manifest_path):
        try:
            content = path.read_bytes()
            rel = path.relative_to(package_dir).as_posix()
        except (OSError, ValueError):
            continue
        digest.update(b"\x00")
        digest.update(rel.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(content)
    return digest.hexdigest()


def _reject_symlinks(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_symlink():
            raise RegenBindingError("Generated package contains a symlink; regen-preview binding refused it.")


def _remove_prior_managed_run(
    workspace_root: Path,
    *,
    package_ref: str | None,
    generation_run_id: str | None,
    current_run_root: Path,
) -> None:
    prior_run_root = _prior_managed_run_root(
        workspace_root,
        package_ref=package_ref,
        generation_run_id=generation_run_id,
    )
    if prior_run_root is None:
        return
    if prior_run_root == current_run_root:
        return
    if prior_run_root.exists():
        shutil.rmtree(prior_run_root)


def _prior_managed_run_root(
    workspace_root: Path,
    *,
    package_ref: str | None,
    generation_run_id: str | None,
) -> Path | None:
    if generation_run_id:
        candidate = workspace_root / DURABLE_SUBDIR / generation_run_id
    elif package_ref:
        managed_package = _resolve_under_workspace(
            workspace_root,
            workspace_root / package_ref,
            "Prior managed package reference is outside the session workspace.",
        )
        candidate = managed_package.parent
    else:
        return None

    durable_root = _resolve_under_workspace(
        workspace_root,
        workspace_root / DURABLE_SUBDIR,
        "Managed artifacts path is outside the session workspace.",
    )
    resolved_candidate = candidate.expanduser().resolve(strict=False)
    if resolved_candidate.parent != durable_root:
        raise RegenBindingError("Prior managed run reference is not a managed-artifacts run.")
    return resolved_candidate
