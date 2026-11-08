"""Studio project file service — local file-based Save/Open.

Provides helpers for:
- building a ``StudioProject`` snapshot from the current ``ProjectSession``
- restoring a ``ProjectSession`` from a ``StudioProject`` snapshot
- serialising / deserialising the snapshot to/from JSON

The snapshot covers Steps 1-6 authoring state plus additive Knowledge
Workspace linkage metadata. Step 8 runtime/build state is intentionally
excluded and remains transient.
"""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from app.models.project import (
    STUDIO_PROJECT_SCHEMA_VERSION,
    BuildRunState,
    IdentityRoleDecision,
    PassthroughFlow,
    ProjectSession,
    StudioProject,
)
from app.services.settings import get_studio_settings

# ---------------------------------------------------------------------------
# Snapshot helpers
# ---------------------------------------------------------------------------

def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_user_hint() -> str | None:
    """Resolve a best-effort local user hint for audit display only."""
    edgeforge_user = os.environ.get("EDGEFORGE_USER")
    if edgeforge_user is not None:
        return edgeforge_user or None
    return os.environ.get("USER") or os.environ.get("USERNAME") or None


def snapshot_session(session: ProjectSession) -> StudioProject:
    """Build a ``StudioProject`` snapshot from the current session.

    Only Steps 1-6 authoring fields are captured.  Step 8 runtime/build state
    (``BuildRunState``, PIDs, ports, log paths, health status) is intentionally
    excluded.
    """
    # passthrough_flow is always present on the session but is only meaningful
    # for passthrough-router archetypes.  Store it so it round-trips cleanly.
    passthrough = session.passthrough_flow if session.app_archetype == "passthrough-router" else None
    kafka_config = session.kafka_config if session.app_archetype == "kafka-integration" else None
    project_id = session.project_id or session.ks_project_id
    ks_active = session.ks_active if session.capabilities.knowledge_assist_enabled else False

    now = _utc_now_iso()
    user = _current_user_hint()

    return StudioProject(
        studio_project_schema_version=STUDIO_PROJECT_SCHEMA_VERSION,
        project_revision=max(1, session.project_revision),
        created_at=session.created_at,
        updated_at=session.updated_at,
        saved_at=now,
        created_by=session.created_by,
        modified_by=user,
        # Step 1
        app_name=session.app_name,
        bounded_context=session.bounded_context,
        app_archetype=session.app_archetype,
        target_profile=session.target_profile,
        output_path=session.output_path,
        appbuilder_repo_path=session.appbuilder_repo_path,
        project_id=project_id,
        ks_project_id=session.ks_project_id,
        ks_active=ks_active,
        capabilities=session.capabilities,
        suggestion_review_state=session.ks_workspace_state.suggestion_review_state,
        evidence_links=list(session.ks_workspace_state.evidence_links),
        manifest_revisions=list(session.ks_workspace_state.manifest_revisions),
        conflict_resolutions=list(session.ks_workspace_state.conflict_resolutions),
        review_history=list(session.ks_workspace_state.review_history),
        # Step 2 — raw spec
        raw_spec_content=session.raw_spec_content,
        raw_spec_url=session.raw_spec_url,
        raw_spec_filename=session.raw_spec_filename,
        # Step 3
        classified_entities=list(session.classified_entities),
        classified_operations=list(session.classified_operations),
        selected_entity_names=list(session.selected_entity_names),
        selected_operation_names=list(session.selected_operation_names),
        identity_role_decisions=list(session.identity_role_decisions),
        # Steps 2-3 upstream
        upstream_interfaces=list(session.upstream_interfaces),
        # Step 4 downstream
        downstream_interfaces=list(session.downstream_interfaces),
        # Step 5 data handoffs
        data_handoffs=list(session.data_handoffs),
        # Step 6 rules + legacy
        entity_rules=list(session.entity_rules),
        auto_rule_merge_completed_entities=list(session.auto_rule_merge_completed_entities),
        legacy_notes=session.legacy_notes,
        legacy_slug=session.legacy_slug,
        # Passthrough flow (only for passthrough archetype)
        passthrough_flow=passthrough,
        kafka_config=kafka_config,
        kafka_topic_pairs=list(session.kafka_topic_pairs),
        kafka_route_models=list(session.kafka_route_models),
        kafka_route_transforms=list(session.kafka_route_transforms),
        # Convenience last-export fields (not authoritative)
        last_export_path=session.last_export_path,
        last_generated_package_ref=session.last_generated_package_ref,
        generation_run_id=session.generation_run_id,
        manifest_hash=session.manifest_hash,
        baseline_hash=session.baseline_hash,
    )


def snapshot_session_for_save(session: ProjectSession, *, save_as: bool = False) -> StudioProject:
    """Prepare a save snapshot and update in-memory save metadata."""
    now = _utc_now_iso()
    user = _current_user_hint()

    if save_as:
        session.project_revision = 1
        session.created_at = now
        session.created_by = user
        session.is_brand_new = False
    elif session.is_brand_new:
        session.project_revision = max(1, session.project_revision)
        if session.created_at is None:
            session.created_at = now
        if session.created_by is None:
            session.created_by = user
        session.is_brand_new = False
    else:
        session.project_revision = max(1, session.project_revision) + 1

    session.updated_at = now
    session.saved_at = now
    session.modified_by = user
    project = snapshot_session(session)
    project.saved_at = now
    project.modified_by = user
    return project


def _copy_save_metadata(source: ProjectSession, target: ProjectSession) -> None:
    target.project_revision = source.project_revision
    target.created_at = source.created_at
    target.updated_at = source.updated_at
    target.saved_at = source.saved_at
    target.created_by = source.created_by
    target.modified_by = source.modified_by
    target.is_brand_new = source.is_brand_new


def restore_session(project: StudioProject, session: ProjectSession) -> None:
    """Restore ``session`` in-place from a ``StudioProject`` snapshot.

    Step 8 runtime/build state is always reset to a fresh ``BuildRunState``
    regardless of what the session previously held.  This prevents stale PIDs,
    ports, log paths, or health status from a previous project carrying over
    into the newly opened one.
    """
    # Always reset Step 8 transient state — must come first so it cannot be
    # accidentally overwritten by the authoring-state restore below.
    session.build_run = BuildRunState()
    # Step 1
    session.app_name = project.app_name
    session.bounded_context = project.bounded_context
    session.app_archetype = project.app_archetype
    session.target_profile = project.target_profile
    session.output_path = project.output_path
    session.appbuilder_repo_path = project.appbuilder_repo_path
    session.project_id = project.project_id
    session.ks_project_id = project.ks_project_id
    session.capabilities = project.capabilities
    session.ks_active = bool(project.capabilities.knowledge_assist_enabled and project.ks_active)
    session.review_approved = False
    session.project_revision = project.project_revision
    session.created_at = project.created_at
    session.updated_at = project.updated_at
    session.saved_at = project.saved_at
    session.created_by = project.created_by
    session.modified_by = project.modified_by
    session.is_brand_new = False
    session.ks_workspace_state = session.ks_workspace_state.__class__(
        suggestion_review_state=project.suggestion_review_state,
        evidence_links=list(project.evidence_links),
        manifest_revisions=list(project.manifest_revisions),
        conflict_resolutions=list(project.conflict_resolutions),
        review_history=list(project.review_history),
    )

    # Step 2 — raw spec
    session.raw_spec_content = project.raw_spec_content
    session.raw_spec_url = project.raw_spec_url
    session.raw_spec_filename = project.raw_spec_filename

    # Step 3
    session.classified_entities = list(project.classified_entities)
    session.classified_operations = list(project.classified_operations)
    session.selected_entity_names = list(project.selected_entity_names)
    session.selected_operation_names = list(project.selected_operation_names)
    session.identity_role_decisions = list(project.identity_role_decisions)

    # Steps 2-3 upstream
    session.upstream_interfaces = list(project.upstream_interfaces)

    # Step 4 downstream
    session.downstream_interfaces = list(project.downstream_interfaces)

    # Step 5 data handoffs
    session.data_handoffs = list(project.data_handoffs)

    # Step 6 rules + legacy
    session.entity_rules = list(project.entity_rules)
    session.auto_rule_merge_completed_entities = list(project.auto_rule_merge_completed_entities)
    session.legacy_notes = project.legacy_notes
    session.legacy_slug = project.legacy_slug

    # Passthrough flow — restore if present, otherwise reset to default
    if project.passthrough_flow is not None:
        session.passthrough_flow = project.passthrough_flow
    else:
        session.passthrough_flow = PassthroughFlow()

    if project.kafka_config is not None:
        session.kafka_config = project.kafka_config
    else:
        session.kafka_config = session.kafka_config.__class__()
    session.kafka_topic_pairs = list(project.kafka_topic_pairs)
    session.kafka_route_models = list(project.kafka_route_models)
    session.kafka_route_transforms = list(project.kafka_route_transforms)

    # Convenience last-export field.
    #
    # SECURITY: this value arrives from an *uploaded* project file, so in shared
    # mode it is untrusted caller input rather than server-owned state. A previous
    # session's export never lives under the current session's server-minted
    # workspace anyway, so carrying it across is not merely unsafe, it is
    # meaningless: the referenced package is not reachable from this session.
    # Drop it and let the operator re-export. ``session_export_dir`` enforces the
    # same boundary on read (defence in depth); this keeps the untrusted value out
    # of session state to begin with.
    #
    # Local mode is unchanged: the path is the operator's own, on their own
    # machine, and reopening a project to download its previous export is a
    # legitimate and expected flow.
    if get_studio_settings().shared_mode:
        session.last_export_path = None
    else:
        session.last_export_path = project.last_export_path
    session.last_generated_package_ref = project.last_generated_package_ref
    session.generation_run_id = project.generation_run_id
    session.manifest_hash = project.manifest_hash
    session.baseline_hash = project.baseline_hash


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def serialize_project(project: StudioProject) -> str:
    """Serialise a ``StudioProject`` to a JSON string."""
    return project.model_dump_json(indent=2)


def save_project(session: ProjectSession, path: str | Path, *, save_as: bool = False) -> StudioProject:
    """Write a project snapshot to ``path`` with backup-before-overwrite semantics."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f"{target.name}.tmp")
    backup_path = target.with_name(f"{target.name}.bak")
    working_session = session.model_copy(deep=True)
    project = snapshot_session_for_save(working_session, save_as=save_as)
    content = serialize_project(project)

    try:
        tmp_path.write_text(content, encoding="utf-8")
        if target.exists() and not save_as:
            shutil.copy2(target, backup_path)
        os.replace(tmp_path, target)
        _copy_save_metadata(working_session, session)
    except Exception:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass
        raise

    return project


def deserialize_project(raw: str) -> StudioProject:
    """Parse and validate a JSON string as a ``StudioProject``.

    Raises:
        ValueError: if the JSON is malformed or the schema version is not
            supported by this version of Studio.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Malformed project file — could not parse JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(
            f"Malformed project file — expected a JSON object, got {type(data).__name__}."
        )

    schema_version = data.get("studio_project_schema_version", "<missing>")
    supported_versions = _supported_project_schema_versions()
    if schema_version not in supported_versions:
        supported_display = "', '".join(sorted(supported_versions))
        raise ValueError(
            f"Unsupported Studio project schema version '{schema_version}'. "
            f"This version of EdgeForge Studio supports version "
            f"'{supported_display}'."
        )

    data = _migrate_project_to_current_schema(data, schema_version=schema_version)
    if "auto_rule_merge_completed_entities" not in data:
        _backfill_auto_rule_merge_completed_entities(data)
    _sanitize_identity_role_decisions(data)

    try:
        return StudioProject.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Invalid project file structure: {exc}") from exc


def _migrate_v1_0_to_v1_1(data: dict) -> dict:
    migrated = dict(data)
    migrated["studio_project_schema_version"] = "1.1"
    migrated.setdefault("project_id", None)
    migrated.setdefault("ks_project_id", None)
    migrated.setdefault("ks_active", False)
    migrated.setdefault(
        "suggestion_review_state",
        {
            "accepted_ids": [],
            "rejected_ids": [],
            "edited_ids": [],
        },
    )
    migrated.setdefault("evidence_links", [])
    migrated.setdefault("manifest_revisions", [])
    migrated.setdefault("conflict_resolutions", [])
    migrated.setdefault("review_history", [])
    return migrated


def _migrate_v1_1_to_v1_2(data: dict) -> dict:
    migrated = dict(data)
    migrated["studio_project_schema_version"] = "1.2"
    capabilities = migrated.setdefault("capabilities", {"knowledge_assist_enabled": False})
    if not isinstance(capabilities, dict):
        capabilities = {"knowledge_assist_enabled": False}
        migrated["capabilities"] = capabilities

    knowledge_assist_enabled = bool(capabilities.get("knowledge_assist_enabled", False))
    capabilities["knowledge_assist_enabled"] = knowledge_assist_enabled
    if not knowledge_assist_enabled:
        migrated["ks_active"] = False
    return migrated


def _migrate_v1_2_to_v1_3(data: dict) -> dict:
    migrated = dict(data)
    migrated["studio_project_schema_version"] = "1.3"
    migrated.setdefault("project_revision", 1)
    migrated.setdefault("created_at", None)
    migrated.setdefault("updated_at", None)
    migrated.setdefault("saved_at", None)
    migrated.setdefault("created_by", None)
    migrated.setdefault("modified_by", None)
    if migrated.get("saved_at") == "":
        migrated["saved_at"] = None
    return migrated


def _migrate_v1_3_to_v1_4(data: dict) -> dict:
    migrated = dict(data)
    migrated["studio_project_schema_version"] = "1.4"
    migrated.setdefault("last_generated_package_ref", None)
    migrated.setdefault("generation_run_id", None)
    migrated.setdefault("manifest_hash", None)
    migrated.setdefault("baseline_hash", None)
    return migrated


_PROJECT_SCHEMA_MIGRATIONS: dict[str, Callable[[dict], dict]] = {
    "1.0": _migrate_v1_0_to_v1_1,
    "1.1": _migrate_v1_1_to_v1_2,
    "1.2": _migrate_v1_2_to_v1_3,
    "1.3": _migrate_v1_3_to_v1_4,
}


def _supported_project_schema_versions() -> set[str]:
    return set(_PROJECT_SCHEMA_MIGRATIONS) | {STUDIO_PROJECT_SCHEMA_VERSION}


def _migrate_project_to_current_schema(data: dict, *, schema_version: str) -> dict:
    migrated = dict(data)
    current_version = schema_version
    while current_version != STUDIO_PROJECT_SCHEMA_VERSION:
        migration = _PROJECT_SCHEMA_MIGRATIONS.get(current_version)
        if migration is None:
            raise ValueError(
                f"Unsupported Studio project schema migration path from '{current_version}' "
                f"to '{STUDIO_PROJECT_SCHEMA_VERSION}'."
            )
        migrated = migration(migrated)
        next_version = migrated.get("studio_project_schema_version")
        if next_version == current_version:
            raise ValueError(
                f"Studio project schema migration for '{current_version}' did not advance."
            )
        current_version = next_version
    return migrated


def _backfill_auto_rule_merge_completed_entities(data: dict) -> None:
    """Treat legacy saved rule buckets as already reviewed by Step 6.

    The auto-rule marker was introduced after users could already save Step 6
    edits.  If an older project has an entity rule bucket, Studio should not
    assume the bucket needs another spec-derived gap-fill on open.
    """
    entity_names: list[str] = []
    for raw_entity_rules in data.get("entity_rules", []) or []:
        if not isinstance(raw_entity_rules, dict):
            continue
        entity_name = str(raw_entity_rules.get("entity_name") or "").strip()
        if entity_name:
            entity_names.append(entity_name)
    data["auto_rule_merge_completed_entities"] = list(dict.fromkeys(entity_names))


def _sanitize_identity_role_decisions(data: dict) -> None:
    """Drop malformed additive identity-role state before project validation."""
    decisions = data.get("identity_role_decisions")
    if not decisions:
        data["identity_role_decisions"] = []
        return
    if not isinstance(decisions, list):
        data["identity_role_decisions"] = []
        return
    valid: list[dict] = []
    for item in decisions:
        if not isinstance(item, dict):
            continue
        try:
            valid.append(IdentityRoleDecision.model_validate(item).model_dump())
        except Exception:
            continue
    data["identity_role_decisions"] = valid
