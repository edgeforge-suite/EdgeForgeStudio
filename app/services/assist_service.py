"""Capability-aware Knowledge Assist access for Studio wizard surfaces."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.integrations.ks_integration import KSCallError, KSUnavailableError
from app.models.project import ProjectSession
from app.services.identity_roles import identity_role_behavior
from app.services.ks_lifecycle import ks_client
from app.services.ks_workspace import (
    current_workspace_identity,
    ensure_workspace_identity,
    mark_workspace_active,
    workspace_allowed_roots,
    workspace_db_path,
)


@dataclass
class FieldSuggestionBadge:
    entity: str
    suggestion_count: int


@dataclass
class Step3FieldReviewContext:
    enabled: bool
    selected_entities: list[str]
    rail_default: str = "collapsed"


@dataclass
class SuggestionBadge:
    scope: str
    label: str
    count: int
    entity: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    drawer_url: str | None = None


@dataclass
class SuggestionDrawerRow:
    suggestion_id: str
    suggestion_type: str
    scope: str
    title: str
    summary: str | None = None
    confidence: float | None = None
    confidence_basis: str | None = None
    manifest_path: str | None = None
    citation_count: int = 0
    status: str = "pending"
    warnings: list[str] = field(default_factory=list)
    payload: dict[str, Any] = field(default_factory=dict)
    has_evidence: bool = False


@dataclass
class SuggestionDrawerScope:
    scope: str
    label: str
    count: int
    rows: list[SuggestionDrawerRow] = field(default_factory=list)


@dataclass
class SuggestionDrawerViewModel:
    ok: bool
    scope: str
    title: str
    entity: str | None = None
    scopes: list[SuggestionDrawerScope] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    empty: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AssistService:
    """Small guard layer between Studio wizard routes and Knowledge Assist."""

    _DRAWER_SCOPE_LABELS = {
        "validations": ("validation hint", "validation hints", "Validation Hints"),
        "rules": ("rule suggestion", "rule suggestions", "Rule Suggestions"),
        "cross_entity_rules": (
            "cross-entity rule suggestion",
            "cross-entity rule suggestions",
            "Cross-Entity Rule Suggestions",
        ),
        "mappings": ("mapping suggestion", "mapping suggestions", "Mapping Suggestions"),
        "transforms": (
            "transform suggestion",
            "transform suggestions",
            "Transform Suggestions",
        ),
        "conflict_resolution": ("conflict", "conflicts", "Conflict Resolution Suggestions"),
        "portfolio_reuse": ("portfolio pattern", "portfolio patterns", "Portfolio Reuse Suggestions"),
        "identity_role": ("identity role suggestion", "identity role suggestions", "Identity Role Suggestions"),
    }

    def is_enabled(self, session: ProjectSession) -> bool:
        return session.capabilities.knowledge_assist_enabled

    def get_step3_field_review_context(
        self,
        session: ProjectSession,
        *,
        selected_entities: list[str],
    ) -> Step3FieldReviewContext:
        enabled = (
            self.is_enabled(session)
            and session.app_archetype == "crud"
            and bool(selected_entities)
            and session.ks_active
            and bool(current_workspace_identity(session))
        )
        return Step3FieldReviewContext(
            enabled=enabled,
            selected_entities=selected_entities,
            rail_default="expanded" if enabled else "collapsed",
        )

    def get_advisory_conflicts(
        self,
        session: ProjectSession,
        *,
        canonical_entities: list[str],
        include_empty_state: bool = True,
    ) -> dict[str, Any]:
        advisories: dict[str, Any] = {
            "enabled": False,
            "available": False,
            "degraded": False,
            "warning": None,
            "groups": [],
            "item_count": 0,
            "entity_count": 0,
            "count": 0,
            "show_empty_state": False,
            "has_items": False,
            "non_blocking": True,
        }
        if session.app_archetype != "crud" or not self.is_enabled(session):
            return advisories

        advisories.update(
            {
                "enabled": True,
                "available": True,
                "show_empty_state": include_empty_state and bool(canonical_entities),
            }
        )
        if not canonical_entities:
            return advisories

        workspace_id = current_workspace_identity(session)
        if not workspace_id or (
            not session.ks_active
            and not session.ks_workspace_state.review_history
            and not session.ks_workspace_state.evidence_links
        ):
            return advisories

        grouped_items: list[dict[str, Any]] = []
        total_items = 0

        try:
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                for canonical_entity in canonical_entities:
                    result = client.suggest_manifest_candidates(
                        project_id=workspace_id,
                        scope="fields",
                        entity=canonical_entity,
                        min_source_count=1,
                        max_suggestions=50,
                    )
                    mark_workspace_active(session)

                    items: list[dict[str, Any]] = []
                    for suggestion in result.get("suggestions", []):
                        conflict_hint = str(suggestion.get("conflict_hint") or "").strip()
                        field_name = str(suggestion.get("field_name") or "").strip()
                        if not conflict_hint or not field_name:
                            continue
                        current_field_name = self._current_field_name(
                            session,
                            canonical_entity,
                            field_name,
                        )
                        if not current_field_name:
                            continue

                        items.append(
                            {
                                "entity": canonical_entity,
                                "field_name": current_field_name,
                                "conflict_hint": conflict_hint,
                                "status": str(suggestion.get("status") or "pending"),
                                "source_count": suggestion.get("source_count"),
                                "consistency_score": suggestion.get("consistency_score"),
                                "suggestion_id": suggestion.get("suggestion_id"),
                                "anchor_id": self._issue_anchor(canonical_entity, current_field_name),
                            }
                        )

                    if not items:
                        continue

                    total_items += len(items)
                    grouped_items.append(
                        {
                            "entity": canonical_entity,
                            "items": items,
                            "visible_items": items[:5],
                            "hidden_items": items[5:],
                            "hidden_count": max(0, len(items) - 5),
                        }
                    )
        except (KSUnavailableError, KSCallError):
            return advisories

        advisories.update(
            {
                "groups": grouped_items,
                "item_count": total_items,
                "count": total_items,
                "entity_count": len(grouped_items),
                "has_items": bool(grouped_items),
            }
        )
        return advisories

    def _issue_anchor(self, entity_name: str, field_name: str) -> str:
        return f"issue-{self._slug(entity_name)}-{self._slug(field_name)}"

    def _slug(self, value: str) -> str:
        return "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-")

    def _field_key(self, value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())

    def _current_field_name(self, session: ProjectSession, canonical_entity: str, field_name: str) -> str | None:
        field_text = str(field_name or "").strip()
        if not field_text:
            return None
        selected_names = set(session.selected_entity_names)
        entity_candidates = [
            entity
            for entity in session.classified_entities
            if entity.name in selected_names and entity.display_name() == canonical_entity
        ] or [
            entity
            for entity in session.classified_entities
            if entity.display_name() == canonical_entity
        ]
        if not entity_candidates:
            return None
        fields = entity_candidates[0].fields
        for candidate_field in fields:
            if candidate_field.name == field_text:
                return candidate_field.name
        field_key = self._field_key(field_text)
        matches = [
            candidate_field.name
            for candidate_field in fields
            if self._field_key(candidate_field.name) == field_key
        ]
        return matches[0] if len(matches) == 1 else None

    def get_field_suggestion_badge(
        self,
        session: ProjectSession,
        *,
        entity: str,
    ) -> FieldSuggestionBadge | None:
        result = self.fetch_field_suggestions(session, entity=entity)
        if not result:
            return None
        suggestion_result = result.get("suggestion_result") or {}
        count = int(
            suggestion_result.get("suggestion_count")
            or len(suggestion_result.get("suggestions", []))
        )
        if count <= 0:
            return None
        return FieldSuggestionBadge(entity=entity, suggestion_count=count)

    def get_validation_hint_badge(
        self,
        session: ProjectSession,
        *,
        entity: str,
    ) -> SuggestionBadge | None:
        return self._get_manifest_suggestion_badge(
            session,
            scope="validations",
            entity=entity,
            label_singular="validation hint",
            label_plural="validation hints",
            drawer_url=f"/entities/ks/drawer?scope=validations&entity={entity}",
        )

    def get_identity_role_suggestion_badge(
        self,
        session: ProjectSession,
        *,
        entity: str,
    ) -> SuggestionBadge | None:
        return self._get_manifest_suggestion_badge(
            session,
            scope="identity_role",
            entity=entity,
            label_singular="identity role suggestion",
            label_plural="identity role suggestions",
            drawer_url=f"/entities/ks/drawer?scope=identity_role&entity={entity}",
        )

    def batch_fetch_step3_badge_counts(
        self,
        session: ProjectSession,
        *,
        validation_entities: list[str],
        identity_entities: list[str],
        max_suggestions: int = 50,
    ) -> tuple[list[SuggestionBadge], list[SuggestionBadge]]:
        if session.app_archetype != "crud" or not self.is_enabled(session):
            return [], []
        if not validation_entities and not identity_entities:
            return [], []

        validation_badges: list[SuggestionBadge] = []
        identity_badges: list[SuggestionBadge] = []

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                for entity in validation_entities:
                    result = self._batch_fetch_manifest_suggestions_with_client(
                        client,
                        session=session,
                        workspace_id=workspace_id,
                        scope="validations",
                        entity=entity,
                        max_suggestions=max_suggestions,
                    )
                    badge = self._manifest_suggestion_badge_from_result(
                        scope="validations",
                        entity=entity,
                        result=result.get("result") if result.get("ok") else None,
                        label_singular="validation hint",
                        label_plural="validation hints",
                        drawer_url=f"/entities/ks/drawer?scope=validations&entity={entity}",
                    )
                    if badge:
                        validation_badges.append(badge)

                for entity in identity_entities:
                    result = self._batch_fetch_manifest_suggestions_with_client(
                        client,
                        session=session,
                        workspace_id=workspace_id,
                        scope="identity_role",
                        entity=entity,
                        max_suggestions=max_suggestions,
                    )
                    badge = self._manifest_suggestion_badge_from_result(
                        scope="identity_role",
                        entity=entity,
                        result=result.get("result") if result.get("ok") else None,
                        label_singular="identity role suggestion",
                        label_plural="identity role suggestions",
                        drawer_url=f"/entities/ks/drawer?scope=identity_role&entity={entity}",
                    )
                    if badge:
                        identity_badges.append(badge)
        except (KSUnavailableError, KSCallError):
            return validation_badges, identity_badges

        return validation_badges, identity_badges

    def get_rule_suggestion_badge(
        self,
        session: ProjectSession,
        *,
        entity: str,
    ) -> SuggestionBadge | None:
        if session.app_archetype != "crud" or not self.is_enabled(session):
            return None

        total = 0
        for scope in ("rules", "cross_entity_rules"):
            result = self._fetch_manifest_suggestions(
                session,
                scope=scope,
                entity=entity,
                max_suggestions=50,
            )
            if not result:
                continue
            total += self._suggestion_count(result)

        if total <= 0:
            return None
        return SuggestionBadge(
            scope="rules",
            label=f"{total} {'rule suggestion' if total == 1 else 'rule suggestions'}",
            count=total,
            entity=entity,
            context={"scopes": ["rules", "cross_entity_rules"]},
            drawer_url=f"/rules/ks/drawer?scope=rules&entity={entity}",
        )

    def get_rule_suggestion_badges_batch(
        self,
        session: ProjectSession,
        *,
        entities: list[str],
        max_suggestions: int = 50,
    ) -> list[SuggestionBadge]:
        if session.app_archetype != "crud" or not self.is_enabled(session):
            return []
        if not entities:
            return []

        badges: list[SuggestionBadge] = []

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                for entity in entities:
                    total = 0
                    for scope in ("rules", "cross_entity_rules"):
                        result = self._batch_fetch_manifest_suggestions_with_client(
                            client,
                            session=session,
                            workspace_id=workspace_id,
                            scope=scope,
                            entity=entity,
                            max_suggestions=max_suggestions,
                        )
                        if result.get("ok") and result.get("result"):
                            total += self._suggestion_count(result["result"])
                    if total <= 0:
                        continue
                    badges.append(
                        SuggestionBadge(
                            scope="rules",
                            label=f"{total} {'rule suggestion' if total == 1 else 'rule suggestions'}",
                            count=total,
                            entity=entity,
                            context={"scopes": ["rules", "cross_entity_rules"]},
                            drawer_url=f"/rules/ks/drawer?scope=rules&entity={entity}",
                        )
                    )
        except (KSUnavailableError, KSCallError):
            return badges

        return badges

    def get_mapping_suggestion_badge(
        self,
        session: ProjectSession,
        *,
        route_name: str,
        direction: str | None = None,
        source_entity: str | None = None,
        target_entity: str | None = None,
        contexts: list[dict[str, Any]] | None = None,
        drawer_url: str | None = None,
    ) -> SuggestionBadge | None:
        if session.app_archetype not in {"passthrough-router", "kafka-integration"}:
            return None
        if not route_name.strip() or not self.is_enabled(session):
            return None

        total = 0
        for context in self._mapping_contexts(
            route_name=route_name,
            direction=direction,
            source_entity=source_entity,
            target_entity=target_entity,
            contexts=contexts,
        ):
            result = self._fetch_manifest_suggestions(
                session,
                scope="mappings",
                entity=None,
                route_name=context["route_name"],
                direction=context["direction"],
                source_entity=context["source_entity"],
                target_entity=context["target_entity"],
                max_suggestions=50,
            )
            if not result:
                continue
            total += self._suggestion_count(result)

        if total <= 0:
            return None
        return SuggestionBadge(
            scope="mappings",
            label=f"{total} {'mapping suggestion' if total == 1 else 'mapping suggestions'}",
            count=total,
            context={
                "route_name": route_name,
                "contexts": self._mapping_contexts(
                    route_name=route_name,
                    direction=direction,
                    source_entity=source_entity,
                    target_entity=target_entity,
                    contexts=contexts,
                ),
            },
            drawer_url=drawer_url,
        )

    def get_transform_suggestion_badge(
        self,
        session: ProjectSession,
        *,
        route_name: str,
        target_id: str,
        direction: str,
        source_entity: str | None = None,
        target_entity: str | None = None,
        contexts: list[dict[str, Any]] | None = None,
        drawer_url: str | None = None,
    ) -> SuggestionBadge | None:
        if session.app_archetype != "kafka-integration" or not self.is_enabled(session):
            return None
        normalized_contexts = self._transform_contexts(
            route_name=route_name,
            target_id=target_id,
            direction=direction,
            source_entity=source_entity,
            target_entity=target_entity,
            contexts=contexts,
        )
        if not normalized_contexts:
            return None

        rows = self._fetch_transform_rows(
            session,
            contexts=normalized_contexts,
            max_suggestions=50,
            include_evidence=False,
        )
        if not rows:
            return None

        count = len(rows)
        direction_label = "request" if direction == "request" else "response"
        return SuggestionBadge(
            scope="transforms",
            label=(
                f"{count} {direction_label} transform "
                f"{'suggestion' if count == 1 else 'suggestions'}"
            ),
            count=count,
            context={
                "route_name": route_name,
                "target_id": target_id,
                "direction": direction,
                "contexts": normalized_contexts,
            },
            drawer_url=drawer_url,
        )

    def get_conflict_resolution_badge(
        self,
        session: ProjectSession,
        *,
        query_candidates: list[str],
        drawer_url: str,
        max_suggestions: int = 10,
    ) -> SuggestionBadge | None:
        rows = self._fetch_conflict_resolution_rows(
            session,
            query_candidates=query_candidates,
            max_suggestions=max_suggestions,
            include_evidence=False,
        )
        if not rows:
            return None
        count = len(rows)
        return SuggestionBadge(
            scope="conflict_resolution",
            label=f"{count} {'conflict' if count == 1 else 'conflicts'}",
            count=count,
            context={"query_candidates": query_candidates[:10]},
            drawer_url=drawer_url,
        )

    def get_portfolio_reuse_badge(
        self,
        session: ProjectSession,
        *,
        query_candidates: list[str],
        drawer_url: str,
        max_suggestions: int = 10,
    ) -> SuggestionBadge | None:
        rows = self._fetch_portfolio_reuse_rows(
            session,
            query_candidates=query_candidates,
            max_suggestions=max_suggestions,
            include_evidence=False,
        )
        if not rows:
            return None
        count = len(rows)
        return SuggestionBadge(
            scope="portfolio_reuse",
            label=f"{count} portfolio {'pattern' if count == 1 else 'patterns'}",
            count=count,
            context={"query_candidates": query_candidates[:10]},
            drawer_url=drawer_url,
        )

    def fetch_suggestion_drawer(
        self,
        session: ProjectSession,
        *,
        scope: str,
        entity: str | None = None,
        route_name: str | None = None,
        direction: str | None = None,
        source_entity: str | None = None,
        target_entity: str | None = None,
    ) -> SuggestionDrawerViewModel | None:
        if scope not in self._DRAWER_SCOPE_LABELS:
            return None
        if not self.is_enabled(session):
            return self._empty_drawer(scope=scope, entity=entity)
        if scope != "mappings" and session.app_archetype != "crud":
            return self._empty_drawer(scope=scope, entity=entity)
        if scope == "mappings" and session.app_archetype not in {
            "passthrough-router",
            "kafka-integration",
        }:
            return self._empty_drawer(scope=scope, entity=entity)

        result = self._fetch_manifest_suggestions(
            session,
            scope=scope,
            entity=entity,
            route_name=route_name,
            direction=direction,
            source_entity=source_entity,
            target_entity=target_entity,
            max_suggestions=50,
        )
        if not result:
            return self._empty_drawer(scope=scope, entity=entity)

        return self.suggestion_drawer_from_result(
            scope=scope,
            entity=entity,
            result=result,
            session=session,
        )

    def suggestion_drawer_from_result(
        self,
        *,
        scope: str,
        entity: str | None,
        result: dict[str, Any],
        session: ProjectSession | None = None,
    ) -> SuggestionDrawerViewModel:
        rows = self._normalize_suggestion_rows(scope=scope, result=result)
        warnings = [str(item) for item in result.get("warnings", []) if str(item).strip()]
        if not rows and scope in {"rules", "cross_entity_rules"} and entity and not warnings and session is not None:
            warnings.append(self._rule_empty_diagnostic(session, entity, (scope,)))
        _, plural, title = self._DRAWER_SCOPE_LABELS[scope]
        drawer_scope = SuggestionDrawerScope(
            scope=scope,
            label=plural.title(),
            count=len(rows),
            rows=rows,
        )
        return SuggestionDrawerViewModel(
            ok=True,
            scope=scope,
            title=title,
            entity=entity,
            scopes=[drawer_scope],
            warnings=warnings,
            empty=len(rows) == 0,
        )

    def batch_fetch_step3_full_review(
        self,
        session: ProjectSession,
        *,
        entities: list[str],
        identity_entities: list[str],
        max_suggestions: int = 50,
    ) -> dict[str, Any]:
        if session.app_archetype != "crud" or not self.is_enabled(session) or not entities:
            return {"ok": True, "project_id": None, "entities": {}, "warnings": []}

        blocks: dict[str, dict[str, Any]] = {
            entity: {
                "field": None,
                "validations": None,
                "identity_role": None,
            }
            for entity in entities
        }
        global_warnings: list[str] = []
        identity_set = set(identity_entities)

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                for entity in entities:
                    blocks[entity]["field"] = self._batch_fetch_field_suggestions_with_client(
                        client,
                        session=session,
                        workspace_id=workspace_id,
                        entity=entity,
                        max_suggestions=max_suggestions,
                    )
                    blocks[entity]["validations"] = self._batch_fetch_manifest_suggestions_with_client(
                        client,
                        session=session,
                        workspace_id=workspace_id,
                        scope="validations",
                        entity=entity,
                        max_suggestions=max_suggestions,
                    )
                    if entity in identity_set:
                        blocks[entity]["identity_role"] = self._batch_fetch_manifest_suggestions_with_client(
                            client,
                            session=session,
                            workspace_id=workspace_id,
                            scope="identity_role",
                            entity=entity,
                            max_suggestions=max_suggestions,
                        )
            return {
                "ok": True,
                "project_id": workspace_id,
                "entities": blocks,
                "warnings": global_warnings,
            }
        except (KSUnavailableError, KSCallError) as exc:
            global_warnings.append(
                f"Knowledge Assist full review batch could not complete: {self._error_message(exc)}"
            )
            return {
                "ok": True,
                "project_id": None,
                "entities": blocks,
                "warnings": global_warnings,
            }

    def _batch_fetch_field_suggestions_with_client(
        self,
        client: Any,
        *,
        session: ProjectSession,
        workspace_id: str,
        entity: str,
        min_source_count: int = 1,
        max_suggestions: int = 50,
    ) -> dict[str, Any]:
        try:
            catalog_result = client.read_field_catalog(
                project_id=workspace_id,
                entity=entity,
            )
            catalog_fields = catalog_result.get("fields", [])
            if not catalog_fields:
                mark_workspace_active(session)
                return {
                    "ok": True,
                    "project_id": workspace_id,
                    "catalog_result": catalog_result,
                    "suggestion_result": None,
                    "warnings": [],
                }

            suggestion_result = client.suggest_manifest_candidates(
                project_id=workspace_id,
                scope="fields",
                entity=entity,
                min_source_count=min_source_count,
                max_suggestions=max_suggestions,
            )
            mark_workspace_active(session)
            return {
                "ok": True,
                "project_id": workspace_id,
                "catalog_result": catalog_result,
                "suggestion_result": suggestion_result,
                "warnings": [],
            }
        except KSCallError as exc:
            return {
                "ok": False,
                "project_id": workspace_id,
                "catalog_result": None,
                "suggestion_result": None,
                "warnings": [f"field suggestions could not be loaded: {self._error_message(exc)}"],
            }

    def _batch_fetch_manifest_suggestions_with_client(
        self,
        client: Any,
        *,
        session: ProjectSession,
        workspace_id: str,
        scope: str,
        entity: str,
        max_suggestions: int = 50,
    ) -> dict[str, Any]:
        try:
            result = client.suggest_manifest_candidates(
                project_id=workspace_id,
                scope=scope,
                entity=entity,
                min_source_count=1,
                max_suggestions=max_suggestions,
            )
            mark_workspace_active(session)
            return {"ok": True, "result": result, "warnings": []}
        except KSCallError as exc:
            return {
                "ok": False,
                "result": None,
                "warnings": [f"{scope} suggestions could not be loaded: {self._error_message(exc)}"],
            }

    def _error_message(self, exc: Exception) -> str:
        return str(exc).strip() or exc.__class__.__name__

    def fetch_mapping_suggestion_drawer(
        self,
        session: ProjectSession,
        *,
        route_name: str,
        direction: str | None = None,
        source_entity: str | None = None,
        target_entity: str | None = None,
        contexts: list[dict[str, Any]] | None = None,
    ) -> SuggestionDrawerViewModel | None:
        if session.app_archetype not in {"passthrough-router", "kafka-integration"}:
            return self._empty_drawer(scope="mappings", entity=None)
        if not self.is_enabled(session):
            return self._empty_drawer(scope="mappings", entity=None)

        drawer_scopes: list[SuggestionDrawerScope] = []
        warnings: list[str] = []
        for context in self._mapping_contexts(
            route_name=route_name,
            direction=direction,
            source_entity=source_entity,
            target_entity=target_entity,
            contexts=contexts,
        ):
            result = self._fetch_manifest_suggestions(
                session,
                scope="mappings",
                entity=None,
                route_name=context["route_name"],
                direction=context["direction"],
                source_entity=context["source_entity"],
                target_entity=context["target_entity"],
                max_suggestions=50,
            )
            if not result:
                continue
            warnings.extend(
                str(item) for item in result.get("warnings", []) if str(item).strip()
            )
            rows = self._normalize_suggestion_rows(scope="mappings", result=result)
            for row in rows:
                payload = dict(row.payload)
                for key in ("route_name", "direction", "source_entity", "target_entity"):
                    payload[key] = payload.get(key) or context.get(key)
                row.payload = payload
            if not rows:
                continue
            drawer_scopes.append(
                SuggestionDrawerScope(
                    scope="mappings",
                    label=self._mapping_scope_label(context),
                    count=len(rows),
                    rows=rows,
                )
            )

        return SuggestionDrawerViewModel(
            ok=True,
            scope="mappings",
            title="Mapping Suggestions",
            entity=None,
            scopes=drawer_scopes,
            warnings=warnings,
            empty=not drawer_scopes,
        )

    def fetch_transform_suggestion_drawer(
        self,
        session: ProjectSession,
        *,
        route_name: str,
        target_id: str,
        direction: str,
        source_entity: str | None = None,
        target_entity: str | None = None,
        contexts: list[dict[str, Any]] | None = None,
    ) -> SuggestionDrawerViewModel | None:
        if session.app_archetype != "kafka-integration":
            return self._empty_drawer(scope="transforms", entity=None)
        if not self.is_enabled(session):
            return self._empty_drawer(scope="transforms", entity=None)

        normalized_contexts = self._transform_contexts(
            route_name=route_name,
            target_id=target_id,
            direction=direction,
            source_entity=source_entity,
            target_entity=target_entity,
            contexts=contexts,
        )
        warnings: list[str] = []
        rows = self._fetch_transform_rows(
            session,
            contexts=normalized_contexts,
            max_suggestions=50,
            include_evidence=True,
            diagnostics=warnings,
        ) if normalized_contexts else []
        if not rows and normalized_contexts and not warnings:
            warnings.extend(
                self._transform_empty_diagnostics(normalized_contexts)
            )
        if not normalized_contexts:
            warnings.append(
                "No Kafka router transform context was available for this drawer request."
            )
        drawer_scope = SuggestionDrawerScope(
            scope="transforms",
            label=self._transform_scope_label(normalized_contexts[0]) if normalized_contexts else "Transform Suggestions",
            count=len(rows),
            rows=rows,
        ) if rows else None
        return SuggestionDrawerViewModel(
            ok=True,
            scope="transforms",
            title="Transform Suggestions",
            entity=None,
            scopes=[drawer_scope] if drawer_scope else [],
            warnings=warnings,
            empty=not rows,
        )

    def fetch_rule_suggestion_drawer(
        self,
        session: ProjectSession,
        *,
        entity: str,
    ) -> SuggestionDrawerViewModel | None:
        if session.app_archetype != "crud" or not self.is_enabled(session):
            return self._empty_drawer(scope="rules", entity=entity)

        drawer_scopes: list[SuggestionDrawerScope] = []
        warnings: list[str] = []
        requested_scopes = ("rules", "cross_entity_rules")
        for scope in requested_scopes:
            result = self._fetch_manifest_suggestions(
                session,
                scope=scope,
                entity=entity,
                max_suggestions=50,
            )
            if not result:
                continue
            warnings.extend(
                str(item) for item in result.get("warnings", []) if str(item).strip()
            )
            rows = self._normalize_suggestion_rows(scope=scope, result=result)
            if not rows:
                continue
            _, plural, _ = self._DRAWER_SCOPE_LABELS[scope]
            drawer_scopes.append(
                SuggestionDrawerScope(
                    scope=scope,
                    label=plural.title(),
                    count=len(rows),
                    rows=rows,
                )
            )
        if not drawer_scopes and not warnings:
            warnings.append(self._rule_empty_diagnostic(session, entity, requested_scopes))

        return SuggestionDrawerViewModel(
            ok=True,
            scope="rules",
            title="Rule Suggestions",
            entity=entity,
            scopes=drawer_scopes,
            warnings=warnings,
            empty=not drawer_scopes,
        )

    def fetch_conflict_resolution_drawer(
        self,
        session: ProjectSession,
        *,
        query_candidates: list[str],
        max_suggestions: int = 10,
    ) -> SuggestionDrawerViewModel | None:
        rows = self._fetch_conflict_resolution_rows(
            session,
            query_candidates=query_candidates,
            max_suggestions=max_suggestions,
            include_evidence=True,
        )
        drawer_scope = SuggestionDrawerScope(
            scope="conflict_resolution",
            label="Conflict Suggestions",
            count=len(rows),
            rows=rows,
        ) if rows else None
        return SuggestionDrawerViewModel(
            ok=True,
            scope="conflict_resolution",
            title="Conflict Resolution Suggestions",
            entity=None,
            scopes=[drawer_scope] if drawer_scope else [],
            warnings=[],
            empty=not rows,
        )

    def fetch_portfolio_reuse_drawer(
        self,
        session: ProjectSession,
        *,
        query_candidates: list[str],
        max_suggestions: int = 10,
    ) -> SuggestionDrawerViewModel | None:
        rows = self._fetch_portfolio_reuse_rows(
            session,
            query_candidates=query_candidates,
            max_suggestions=max_suggestions,
            include_evidence=True,
        )
        drawer_scope = SuggestionDrawerScope(
            scope="portfolio_reuse",
            label="Portfolio Patterns",
            count=len(rows),
            rows=rows,
        ) if rows else None
        return SuggestionDrawerViewModel(
            ok=True,
            scope="portfolio_reuse",
            title="Portfolio Reuse Suggestions",
            entity=None,
            scopes=[drawer_scope] if drawer_scope else [],
            warnings=[],
            empty=not rows,
        )

    def submit_rule_suggestion_decisions(
        self,
        session: ProjectSession,
        *,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if session.app_archetype != "crud" or not self.is_enabled(session):
            return None

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                result = client.submit_suggestion_decisions(
                    project_id=workspace_id,
                    decisions=decisions,
                )
                mark_workspace_active(session)
                return result
        except (KSUnavailableError, KSCallError):
            return None

    def submit_validation_suggestion_decisions(
        self,
        session: ProjectSession,
        *,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if session.app_archetype != "crud" or not self.is_enabled(session):
            return None

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                result = client.submit_suggestion_decisions(
                    project_id=workspace_id,
                    decisions=decisions,
                )
                mark_workspace_active(session)
                return result
        except (KSUnavailableError, KSCallError):
            return None

    def submit_identity_role_suggestion_decisions(
        self,
        session: ProjectSession,
        *,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if session.app_archetype != "crud" or not self.is_enabled(session):
            return None

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                result = client.submit_suggestion_decisions(
                    project_id=workspace_id,
                    decisions=decisions,
                )
                mark_workspace_active(session)
                return result
        except (KSUnavailableError, KSCallError):
            return None

    def submit_mapping_suggestion_decisions(
        self,
        session: ProjectSession,
        *,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if session.app_archetype not in {"passthrough-router", "kafka-integration"}:
            return None
        if not self.is_enabled(session):
            return None

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                result = client.submit_suggestion_decisions(
                    project_id=workspace_id,
                    decisions=decisions,
                )
                mark_workspace_active(session)
                return result
        except (KSUnavailableError, KSCallError):
            return None

    def submit_transform_suggestion_decisions(
        self,
        session: ProjectSession,
        *,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if session.app_archetype != "kafka-integration" or not self.is_enabled(session):
            return None

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                result = client.submit_suggestion_decisions(
                    project_id=workspace_id,
                    decisions=decisions,
                )
                mark_workspace_active(session)
                return result
        except (KSUnavailableError, KSCallError):
            return None

    def submit_conflict_resolution_decisions(
        self,
        session: ProjectSession,
        *,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not self.is_enabled(session):
            return None

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                result = client.submit_suggestion_decisions(
                    project_id=workspace_id,
                    decisions=decisions,
                )
                mark_workspace_active(session)
                return result
        except (KSUnavailableError, KSCallError):
            return None

    def submit_portfolio_reuse_decisions(
        self,
        session: ProjectSession,
        *,
        decisions: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if not self.is_enabled(session):
            return None

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                result = client.submit_suggestion_decisions(
                    project_id=workspace_id,
                    decisions=decisions,
                )
                mark_workspace_active(session)
                return result
        except (KSUnavailableError, KSCallError):
            return None

    def _get_manifest_suggestion_badge(
        self,
        session: ProjectSession,
        *,
        scope: str,
        entity: str,
        label_singular: str,
        label_plural: str,
        drawer_url: str,
    ) -> SuggestionBadge | None:
        if session.app_archetype != "crud" or not self.is_enabled(session):
            return None
        result = self._fetch_manifest_suggestions(
            session,
            scope=scope,
            entity=entity,
            max_suggestions=50,
        )
        if not result:
            return None
        return self._manifest_suggestion_badge_from_result(
            scope=scope,
            entity=entity,
            result=result,
            label_singular=label_singular,
            label_plural=label_plural,
            drawer_url=drawer_url,
        )

    def _manifest_suggestion_badge_from_result(
        self,
        *,
        scope: str,
        entity: str,
        result: dict[str, Any] | None,
        label_singular: str,
        label_plural: str,
        drawer_url: str,
    ) -> SuggestionBadge | None:
        if not result:
            return None
        count = self._suggestion_count(result)
        if count <= 0:
            return None
        return SuggestionBadge(
            scope=scope,
            label=f"{count} {label_singular if count == 1 else label_plural}",
            count=count,
            entity=entity,
            drawer_url=drawer_url,
        )

    def _fetch_manifest_suggestions(
        self,
        session: ProjectSession,
        *,
        scope: str,
        entity: str | None,
        route_name: str | None = None,
        target_id: str | None = None,
        direction: str | None = None,
        source_entity: str | None = None,
        target_entity: str | None = None,
        field_name_pattern: str | None = None,
        max_suggestions: int = 50,
    ) -> dict[str, Any] | None:
        if not self.is_enabled(session):
            return None
        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                arguments: dict[str, Any] = {
                    "project_id": workspace_id,
                    "scope": scope,
                    "min_source_count": 1,
                    "max_suggestions": max_suggestions,
                }
                if entity is not None:
                    arguments["entity"] = entity
                if route_name is not None:
                    arguments["route_name"] = route_name
                if target_id is not None:
                    arguments["target_id"] = target_id
                if direction is not None:
                    arguments["direction"] = direction
                if source_entity is not None:
                    arguments["source_entity"] = source_entity
                if target_entity is not None:
                    arguments["target_entity"] = target_entity
                if field_name_pattern is not None:
                    arguments["field_name_pattern"] = field_name_pattern
                result = client.suggest_manifest_candidates(**arguments)
                mark_workspace_active(session)
                return result
        except (KSUnavailableError, KSCallError):
            return None

    def _fetch_conflict_resolution_rows(
        self,
        session: ProjectSession,
        *,
        query_candidates: list[str],
        max_suggestions: int,
        include_evidence: bool,
    ) -> list[SuggestionDrawerRow]:
        if not self.is_enabled(session):
            return []

        queries = self._dedupe_text(query_candidates)[:10]
        if not queries:
            return []

        rows: list[SuggestionDrawerRow] = []
        seen_ids: set[str] = set()
        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                for query in queries:
                    if len(rows) >= max_suggestions:
                        break
                    result = client.suggest_manifest_candidates(
                        project_id=workspace_id,
                        scope="conflict_resolution",
                        field_name_pattern=query,
                        min_source_count=1,
                        max_suggestions=max_suggestions,
                    )
                    raw_suggestions = result.get("suggestions", [])
                    if not isinstance(raw_suggestions, list):
                        continue
                    for suggestion in raw_suggestions:
                        if len(rows) >= max_suggestions:
                            break
                        if not isinstance(suggestion, dict):
                            continue
                        suggestion_id = str(suggestion.get("suggestion_id") or "").strip()
                        if not suggestion_id or suggestion_id in seen_ids:
                            continue
                        seen_ids.add(suggestion_id)
                        evidence_result = None
                        if include_evidence:
                            try:
                                evidence_result = client.get_suggestion_evidence_chain(
                                    project_id=workspace_id,
                                    scope="conflict_resolution",
                                    suggestion_id=suggestion_id,
                                )
                            except (KSUnavailableError, KSCallError):
                                evidence_result = None
                        rows.append(
                            self._normalize_conflict_resolution_row(
                                suggestion=suggestion,
                                query=query,
                                evidence_result=evidence_result,
                            )
                        )
                mark_workspace_active(session)
        except (KSUnavailableError, KSCallError):
            return []
        return rows

    def _fetch_portfolio_reuse_rows(
        self,
        session: ProjectSession,
        *,
        query_candidates: list[str],
        max_suggestions: int,
        include_evidence: bool,
    ) -> list[SuggestionDrawerRow]:
        if not self.is_enabled(session):
            return []

        queries = self._dedupe_text(query_candidates)[:10]
        if not queries:
            return []

        rows: list[SuggestionDrawerRow] = []
        seen_ids: set[str] = set()
        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                for query in queries:
                    if len(rows) >= max_suggestions:
                        break
                    result = client.suggest_manifest_candidates(
                        project_id=workspace_id,
                        scope="portfolio_reuse",
                        field_name_pattern=query,
                        min_source_count=1,
                        max_suggestions=max_suggestions,
                    )
                    raw_suggestions = result.get("suggestions", [])
                    if not isinstance(raw_suggestions, list):
                        continue
                    for suggestion in raw_suggestions:
                        if len(rows) >= max_suggestions:
                            break
                        if not isinstance(suggestion, dict):
                            continue
                        suggestion_id = str(suggestion.get("suggestion_id") or "").strip()
                        if not suggestion_id or suggestion_id in seen_ids:
                            continue
                        seen_ids.add(suggestion_id)
                        evidence_result = None
                        if include_evidence:
                            try:
                                evidence_result = client.get_suggestion_evidence_chain(
                                    project_id=workspace_id,
                                    scope="portfolio_reuse",
                                    suggestion_id=suggestion_id,
                                )
                            except (KSUnavailableError, KSCallError):
                                evidence_result = None
                        rows.append(
                            self._normalize_portfolio_reuse_row(
                                suggestion=suggestion,
                                query=query,
                                evidence_result=evidence_result,
                            )
                        )
                mark_workspace_active(session)
        except (KSUnavailableError, KSCallError):
            return []
        return rows

    def _fetch_transform_rows(
        self,
        session: ProjectSession,
        *,
        contexts: list[dict[str, str]],
        max_suggestions: int,
        include_evidence: bool,
        diagnostics: list[str] | None = None,
    ) -> list[SuggestionDrawerRow]:
        if not self.is_enabled(session) or not contexts:
            return []

        rows: list[SuggestionDrawerRow] = []
        seen_ids: set[str] = set()
        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                for context in contexts:
                    if len(rows) >= max_suggestions:
                        break
                    result = client.suggest_manifest_candidates(
                        project_id=workspace_id,
                        scope="transforms",
                        route_name=context["route_name"],
                        target_id=context["target_id"],
                        direction=context["direction"],
                        source_entity=context["source_entity"],
                        target_entity=context["target_entity"],
                        min_source_count=1,
                        max_suggestions=max_suggestions,
                    )
                    context_warnings = [
                        str(item)
                        for item in result.get("warnings", []) or []
                        if str(item or "").strip()
                    ]
                    if diagnostics is not None and context_warnings:
                        diagnostics.extend(
                            f"{self._transform_context_label(context)}: {warning}"
                            for warning in context_warnings
                        )
                    raw_suggestions = result.get("suggestions", [])
                    if not isinstance(raw_suggestions, list):
                        if diagnostics is not None:
                            diagnostics.append(
                                f"{self._transform_context_label(context)}: Knowledge Assist returned malformed transform suggestions."
                            )
                        continue
                    for suggestion in raw_suggestions:
                        if len(rows) >= max_suggestions:
                            break
                        if not isinstance(suggestion, dict):
                            continue
                        suggestion_id = str(suggestion.get("suggestion_id") or "").strip()
                        if not suggestion_id or suggestion_id in seen_ids:
                            continue
                        seen_ids.add(suggestion_id)
                        evidence_result = None
                        if include_evidence:
                            try:
                                evidence_result = client.get_suggestion_evidence_chain(
                                    project_id=workspace_id,
                                    scope="transforms",
                                    suggestion_id=suggestion_id,
                                )
                            except (KSUnavailableError, KSCallError):
                                evidence_result = None
                        rows.append(
                            self._normalize_transform_row(
                                suggestion=suggestion,
                                context=context,
                                evidence_result=evidence_result,
                            )
                        )
                mark_workspace_active(session)
        except (KSUnavailableError, KSCallError):
            return []
        return rows

    def _rule_empty_diagnostic(
        self,
        session: ProjectSession,
        entity: str,
        scopes: tuple[str, ...],
    ) -> str:
        fields = self._current_field_names(session, entity)
        if fields:
            return (
                f"No rule suggestions are currently available for {entity}. "
                f"Studio checked the current {entity} fields but did not find actionable rule suggestions. "
                "Check that Knowledge Assist documents have been ingested in the Knowledge Workspace."
            )
        return (
            f"No rule suggestions are currently available for {entity}. "
            "Add fields to the current CRUD model and ingest supporting Knowledge Assist documents to surface suggestions."
        )

    def _current_field_names(self, session: ProjectSession, canonical_entity: str) -> list[str]:
        selected_names = set(session.selected_entity_names)
        for entity in session.classified_entities:
            if entity.name in selected_names and entity.display_name() == canonical_entity:
                return [field.name for field in entity.fields]
        for entity in session.classified_entities:
            if entity.display_name() == canonical_entity:
                return [field.name for field in entity.fields]
        return []

    def _transform_context_label(self, context: dict[str, str]) -> str:
        route_name = context.get("route_name") or "unknown route"
        target_id = context.get("target_id") or "unknown target"
        direction = (context.get("direction") or "transform").strip()
        source = context.get("source_entity") or "source"
        target = context.get("target_entity") or "target"
        return f"{route_name} target {target_id} {direction} transform ({source} -> {target})"

    def _transform_empty_diagnostics(self, contexts: list[dict[str, str]]) -> list[str]:
        return [
            f"No actionable Kafka transform suggestions are currently available for {self._transform_context_label(context)}."
            for context in contexts
        ]

    def _has_evidence_material(
        self,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
        *,
        citation_count: int,
    ) -> bool:
        if citation_count > 0:
            return True
        if self._conflict_snippets(suggestion, payload):
            return True
        for key in ("citations", "evidence_chunks", "source_documents", "sources"):
            value = suggestion.get(key)
            if value is None:
                value = payload.get(key)
            if isinstance(value, list) and value:
                return True
            if isinstance(value, dict) and value:
                return True
        return False

    def _mapping_contexts(
        self,
        *,
        route_name: str,
        direction: str | None = None,
        source_entity: str | None = None,
        target_entity: str | None = None,
        contexts: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        raw_contexts = contexts or [
            {
                "route_name": route_name,
                "direction": direction,
                "source_entity": source_entity,
                "target_entity": target_entity,
            }
        ]
        normalized: list[dict[str, str]] = []
        for context in raw_contexts:
            current = {
                "route_name": str(context.get("route_name") or route_name or "").strip(),
                "direction": str(context.get("direction") or "").strip(),
                "source_entity": str(context.get("source_entity") or "").strip(),
                "target_entity": str(context.get("target_entity") or "").strip(),
            }
            if all(current.values()):
                normalized.append(current)
        return normalized

    def _transform_contexts(
        self,
        *,
        route_name: str,
        target_id: str,
        direction: str,
        source_entity: str | None = None,
        target_entity: str | None = None,
        contexts: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        raw_contexts = contexts or [
            {
                "route_name": route_name,
                "target_id": target_id,
                "direction": direction,
                "source_entity": source_entity,
                "target_entity": target_entity,
            }
        ]
        normalized: list[dict[str, str]] = []
        for context in raw_contexts:
            current = {
                "route_name": str(context.get("route_name") or route_name or "").strip(),
                "target_id": str(context.get("target_id") or target_id or "").strip(),
                "direction": str(context.get("direction") or direction or "").strip(),
                "source_entity": str(context.get("source_entity") or "").strip(),
                "target_entity": str(context.get("target_entity") or "").strip(),
            }
            if (
                current["route_name"]
                and current["target_id"]
                and current["direction"] in {"request", "response"}
                and current["source_entity"]
                and current["target_entity"]
            ):
                normalized.append(current)
        return normalized

    def _mapping_scope_label(self, context: dict[str, str]) -> str:
        direction = context.get("direction", "").strip().title()
        source = context.get("source_entity", "").strip()
        target = context.get("target_entity", "").strip()
        if direction and source and target:
            return f"{direction} Mappings: {source} → {target}"
        return "Mapping Suggestions"

    def _transform_scope_label(self, context: dict[str, str]) -> str:
        target_id = context.get("target_id", "").strip()
        direction = context.get("direction", "").strip().title()
        source = context.get("source_entity", "").strip()
        target = context.get("target_entity", "").strip()
        label = f"{direction} Transform Suggestions" if direction else "Transform Suggestions"
        if target_id:
            label = f"{label}: {target_id}"
        if source and target:
            label = f"{label} ({source} → {target})"
        return label

    def _dedupe_text(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            text = str(value or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

    def _suggestion_count(self, result: dict[str, Any]) -> int:
        suggestions = result.get("suggestions", [])
        try:
            return int(result.get("suggestion_count") or len(suggestions))
        except (TypeError, ValueError):
            return len(suggestions) if isinstance(suggestions, list) else 0

    def _empty_drawer(self, *, scope: str, entity: str | None) -> SuggestionDrawerViewModel:
        _, _, title = self._DRAWER_SCOPE_LABELS.get(scope, (scope, scope, "Suggestions"))
        return SuggestionDrawerViewModel(
            ok=True,
            scope=scope,
            title=title,
            entity=entity,
            scopes=[],
            warnings=[],
            empty=True,
        )

    def _normalize_suggestion_rows(
        self,
        *,
        scope: str,
        result: dict[str, Any],
    ) -> list[SuggestionDrawerRow]:
        rows: list[SuggestionDrawerRow] = []
        raw_suggestions = result.get("suggestions", [])
        if not isinstance(raw_suggestions, list):
            return rows

        for index, suggestion in enumerate(raw_suggestions):
            if not isinstance(suggestion, dict):
                continue
            raw_payload = suggestion.get("payload")
            payload = dict(raw_payload) if isinstance(raw_payload, dict) else dict(suggestion)
            if isinstance(raw_payload, dict):
                for key in (
                    "field",
                    "field_name",
                    "target_field",
                    "source_field",
                    "validation_type",
                    "rule_type",
                    "type",
                    "constraint",
                    "manifest_path",
                    "route_name",
                    "target_id",
                    "direction",
                    "source",
                    "target",
                    "default_value",
                    "constant",
                    "value_map",
                    "type_coercion",
                    "entity",
                    "entity_name",
                    "canonical_entity",
                    "suggested_role",
                    "role",
                    "identity_role",
                    "signals",
                    "source_document_ids",
                    "source_document_names",
                    "review_needed",
                    "conflicting_roles",
                ):
                    if key not in payload and key in suggestion:
                        payload[key] = suggestion[key]
            suggestion_id = str(
                suggestion.get("suggestion_id")
                or payload.get("suggestion_id")
                or f"{scope}-{index + 1}"
            )
            suggestion_type = str(
                suggestion.get("suggestion_type")
                or payload.get("suggestion_type")
                or scope
            )
            if scope == "mappings" and suggestion_type == "mappings":
                suggestion_type = "mapping"
            if scope == "transforms" and suggestion_type == "transforms":
                suggestion_type = "transform"
            if scope == "identity_role":
                suggestion_type = "identity_role"
                entity = self._first_text(
                    suggestion,
                    payload,
                    ("entity", "entity_name", "canonical_entity"),
                )
                field = self._first_text(
                    suggestion,
                    payload,
                    ("field", "field_name", "target_field"),
                )
                role = self._first_text(
                    suggestion,
                    payload,
                    ("suggested_role", "role", "identity_role"),
                )
                payload = dict(payload)
                if entity:
                    payload["entity"] = entity
                if field:
                    payload["field"] = field
                    payload.setdefault("field_name", field)
                if role:
                    payload["suggested_role"] = role
                    payload.setdefault("role", role)
                review_needed = bool(payload.get("review_needed") or suggestion.get("review_needed"))
                behavior = identity_role_behavior(role)
                export_impact = " ".join(
                    str(behavior.get(key) or "").strip()
                    for key in ("current_engine_behavior", "export_behavior", "api_behavior")
                    if str(behavior.get(key) or "").strip()
                )
                payload["suggestion_semantics"] = {
                    "category": (
                        "Review needed"
                        if review_needed
                        else "Applies generated change"
                        if role == "persistence_id"
                        else "Advisory only"
                    ),
                    "export_impact": export_impact,
                }
            title = self._suggestion_title(scope, suggestion, payload)
            summary = self._first_text(
                suggestion,
                payload,
                ("summary", "rationale", "description", "conflict_hint", "message"),
            )
            manifest_path = self._first_text(
                suggestion,
                payload,
                ("manifest_path", "target_manifest_path", "path"),
            )
            confidence = self._coerce_confidence(
                suggestion.get("confidence")
                if suggestion.get("confidence") is not None
                else suggestion.get("confidence_score")
                if suggestion.get("confidence_score") is not None
                else suggestion.get("consistency_score")
            )
            confidence_basis = self._first_text(
                suggestion,
                payload,
                ("confidence_basis", "confidence_reason", "basis"),
            )
            if scope == "mappings" and confidence_basis and not payload.get("confidence_basis"):
                payload = dict(payload)
                payload["confidence_basis"] = confidence_basis
            citation_count = self._citation_count(suggestion, payload)
            has_evidence = self._has_evidence_material(
                suggestion,
                payload,
                citation_count=citation_count,
            )
            warnings = [
                str(item)
                for item in suggestion.get("warnings", payload.get("warnings", [])) or []
                if str(item).strip()
            ]
            rows.append(
                SuggestionDrawerRow(
                    suggestion_id=suggestion_id,
                    suggestion_type=suggestion_type,
                    scope=scope,
                    title=title,
                    summary=summary,
                    confidence=confidence,
                    confidence_basis=confidence_basis,
                    manifest_path=manifest_path,
                    citation_count=citation_count,
                    status=str(suggestion.get("status") or payload.get("status") or "pending"),
                    warnings=warnings,
                    payload=payload,
                    has_evidence=has_evidence,
                )
            )
        return rows

    def _normalize_transform_row(
        self,
        *,
        suggestion: dict[str, Any],
        context: dict[str, str],
        evidence_result: dict[str, Any] | None,
    ) -> SuggestionDrawerRow:
        row = self._normalize_suggestion_rows(
            scope="transforms",
            result={"suggestions": [suggestion]},
        )[0]
        payload = dict(row.payload)
        for key in ("route_name", "target_id", "direction", "source_entity", "target_entity"):
            payload[key] = payload.get(key) or context.get(key)

        snippets = self._conflict_snippets(suggestion, payload)
        evidence_citation_count = 0
        if isinstance(evidence_result, dict):
            evidence_citation_count = self._evidence_citation_count(evidence_result)
            snippets.extend(self._conflict_snippets(evidence_result, evidence_result))

        snippets = self._dedupe_text(snippets)[:3]
        if snippets:
            payload["snippets"] = snippets

        row.payload = payload
        row.citation_count = max(row.citation_count, evidence_citation_count)
        row.has_evidence = row.citation_count > 0 or bool(snippets)
        if not row.summary:
            row.summary = "Suggested transform row. Review only; no changes are applied until you accept or edit this suggestion."
        if snippets:
            row.summary = f"{row.summary} Evidence: {snippets[0]}"
        return row

    def _normalize_conflict_resolution_row(
        self,
        *,
        suggestion: dict[str, Any],
        query: str,
        evidence_result: dict[str, Any] | None,
    ) -> SuggestionDrawerRow:
        row = self._normalize_suggestion_rows(
            scope="conflict_resolution",
            result={"suggestions": [suggestion]},
        )[0]
        payload = dict(row.payload)
        payload["conflict_query"] = query

        document_labels = self._conflict_document_labels(suggestion, payload)
        document_ids = self._conflict_document_ids(suggestion, payload)
        document_options = self._conflict_document_options(suggestion, payload)
        snippets = self._conflict_snippets(suggestion, payload)
        evidence_citation_count = 0
        if isinstance(evidence_result, dict):
            evidence_citation_count = self._evidence_citation_count(evidence_result)
            document_labels.extend(self._conflict_document_labels(evidence_result, evidence_result))
            document_ids.extend(self._conflict_document_ids(evidence_result, evidence_result))
            document_options.extend(self._conflict_document_options(evidence_result, evidence_result))
            snippets.extend(self._conflict_snippets(evidence_result, evidence_result))

        document_labels = self._dedupe_text(document_labels)
        document_ids = self._dedupe_text(document_ids)
        document_options = self._dedupe_document_options(document_options, document_ids, document_labels)
        snippets = self._dedupe_text(snippets)[:3]
        conflict_entity = self._first_text(
            suggestion,
            payload,
            ("entity", "entity_name", "canonical_entity", "source_entity"),
        )
        conflict_field = self._first_text(
            suggestion,
            payload,
            ("field", "field_name", "target_field", "source_field"),
        )
        difference_category = self._conflict_difference_category(suggestion, payload, snippets)
        normalized_mapping = self._conflict_normalized_mapping(suggestion, payload)
        conflict_summary = self._conflict_delta_summary(
            suggestion,
            payload,
            query=query,
            entity=conflict_entity,
            field=conflict_field,
            difference_category=difference_category,
            normalized_mapping=normalized_mapping,
            document_labels=document_labels,
            snippets=snippets,
        )
        if document_labels:
            payload["document_labels"] = document_labels
        if document_ids:
            payload["document_ids"] = document_ids
        if document_options:
            payload["document_options"] = document_options
        if snippets:
            payload["snippets"] = snippets
        if conflict_entity:
            payload["entity"] = conflict_entity
        if conflict_field:
            payload["field"] = conflict_field
        if difference_category:
            payload["difference_category"] = difference_category
        if normalized_mapping:
            payload["normalized_field_mapping"] = normalized_mapping
        payload["conflict_summary"] = conflict_summary
        row.payload = payload
        row.citation_count = max(row.citation_count, evidence_citation_count)
        row.has_evidence = row.citation_count > 0 or bool(snippets)
        row.summary = conflict_summary
        return row

    def _normalize_portfolio_reuse_row(
        self,
        *,
        suggestion: dict[str, Any],
        query: str,
        evidence_result: dict[str, Any] | None,
    ) -> SuggestionDrawerRow:
        row = self._normalize_suggestion_rows(
            scope="portfolio_reuse",
            result={"suggestions": [suggestion]},
        )[0]
        payload = dict(row.payload)
        payload["portfolio_query"] = query

        matched_project_id = self._first_text(
            suggestion,
            payload,
            ("matched_project_id", "source_project_id", "source_project", "project_id"),
        )
        reuse_kind = self._first_text(
            suggestion,
            payload,
            ("reuse_kind", "pattern_type", "kind", "suggestion_type"),
        )
        document_labels = self._conflict_document_labels(suggestion, payload)
        document_ids = self._conflict_document_ids(suggestion, payload)
        snippets = self._conflict_snippets(suggestion, payload)
        evidence_citation_count = 0
        if isinstance(evidence_result, dict):
            evidence_citation_count = self._evidence_citation_count(evidence_result)
            document_labels.extend(self._conflict_document_labels(evidence_result, evidence_result))
            document_ids.extend(self._conflict_document_ids(evidence_result, evidence_result))
            snippets.extend(self._conflict_snippets(evidence_result, evidence_result))

        document_labels = self._dedupe_text(document_labels)
        document_ids = self._dedupe_text(document_ids)
        snippets = self._dedupe_text(snippets)[:3]
        if matched_project_id:
            payload["matched_project_id"] = matched_project_id
        if reuse_kind:
            payload["reuse_kind"] = reuse_kind
        if document_labels:
            payload["document_labels"] = document_labels
        if document_ids:
            payload["document_ids"] = document_ids
        if snippets:
            payload["snippets"] = snippets

        row.payload = payload
        row.citation_count = max(row.citation_count, evidence_citation_count)
        row.has_evidence = row.citation_count > 0 or bool(snippets)
        if not row.summary:
            row.summary = "Portfolio pattern from another indexed project. Review only; nothing is imported or applied yet."
        if matched_project_id:
            row.summary = f"{row.summary} Source project: {matched_project_id}."
        if document_labels:
            row.summary = f"{row.summary} Documents: {', '.join(document_labels[:3])}."
        if snippets:
            row.summary = f"{row.summary} Evidence: {snippets[0]}"
        return row

    def _suggestion_title(
        self,
        scope: str,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
    ) -> str:
        if scope == "mappings":
            explicit_title = self._first_text(suggestion, payload, ("title",))
            if explicit_title:
                return explicit_title
            source = self._first_text(
                suggestion,
                payload,
                ("source_field", "source", "from", "input_field"),
            )
            target = self._first_text(
                suggestion,
                payload,
                ("target_field", "target", "to", "output_field"),
            )
            if source and target:
                return f"{source} → {target}"
            summary = self._first_text(suggestion, payload, ("summary",))
            return summary or "Mapping suggestion"

        if scope == "transforms":
            explicit_title = self._first_text(suggestion, payload, ("title",))
            if explicit_title:
                return explicit_title
            source = self._first_text(
                suggestion,
                payload,
                ("source_field", "source", "from", "input_field"),
            )
            target = self._first_text(
                suggestion,
                payload,
                ("target_field", "target", "to", "output_field"),
            )
            if source and target:
                return f"{source} → {target}"
            return "Suggested transform row"

        if scope == "conflict_resolution":
            explicit_title = self._first_text(
                suggestion,
                payload,
                ("title", "conflict_signal", "signal", "summary"),
            )
            return explicit_title or "Conflict for human review"

        if scope == "portfolio_reuse":
            explicit_title = self._first_text(
                suggestion,
                payload,
                ("title", "pattern_name", "reuse_kind", "summary"),
            )
            return explicit_title or "Portfolio pattern from another indexed project"

        if scope == "identity_role":
            explicit_title = self._first_text(suggestion, payload, ("title", "summary"))
            if explicit_title:
                return explicit_title
            entity = self._first_text(suggestion, payload, ("entity", "entity_name", "canonical_entity"))
            field = self._first_text(suggestion, payload, ("field", "field_name", "target_field"))
            role = self._first_text(suggestion, payload, ("suggested_role", "role", "identity_role"))
            if entity and field and role:
                return f"{entity}.{field} → {role}"
            if field and role:
                return f"{field} → {role}"
            return "Identity role suggestion"

        explicit = self._first_text(suggestion, payload, ("title", "summary"))
        if explicit:
            return explicit
        if scope == "validations":
            target = self._first_text(suggestion, payload, ("field_name", "field", "target"))
            return f"Validation hint for {target}" if target else "Validation hint"
        if scope == "cross_entity_rules":
            rule_type = self._first_text(suggestion, payload, ("rule_type", "type"))
            field = self._first_text(suggestion, payload, ("field_name", "field"))
            if rule_type and field:
                return f"{rule_type} on {field}"
            return "Cross-entity rule suggestion"
        if scope == "rules":
            rule_type = self._first_text(suggestion, payload, ("rule_type", "type"))
            field = self._first_text(suggestion, payload, ("field_name", "field"))
            if rule_type and field:
                return f"{rule_type} on {field}"
            return "Rule suggestion"
        return "Suggestion"

    def _conflict_document_labels(
        self,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[str]:
        labels: list[str] = []
        for key in ("document_name", "document_id"):
            value = suggestion.get(key)
            if value is None:
                value = payload.get(key)
            if value:
                labels.append(str(value).strip())
        for key in ("document_names", "document_ids", "source_document_ids", "documents", "document_refs"):
            value = suggestion.get(key)
            if value is None:
                value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        labels.append(
                            str(
                                item.get("document_name")
                                or item.get("name")
                                or item.get("document_id")
                                or item.get("id")
                                or ""
                            ).strip()
                        )
                    else:
                        labels.append(str(item).strip())
            elif isinstance(value, dict):
                labels.append(
                    str(value.get("document_name") or value.get("name") or value.get("document_id") or value.get("id") or "").strip()
                )
            elif value:
                labels.append(str(value).strip())

        chunks = suggestion.get("evidence_chunks") or payload.get("evidence_chunks") or []
        if isinstance(chunks, list):
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                citation = chunk.get("citation") if isinstance(chunk.get("citation"), dict) else {}
                labels.append(
                    str(
                        chunk.get("document_name")
                        or chunk.get("document_id")
                        or citation.get("document_name")
                        or citation.get("document_id")
                        or ""
                    ).strip()
                )
        return [label for label in labels if label]

    def _conflict_document_ids(
        self,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[str]:
        ids: list[str] = []
        for key in ("document_id",):
            value = suggestion.get(key)
            if value is None:
                value = payload.get(key)
            if value:
                ids.append(str(value).strip())
        for key in ("document_ids", "source_document_ids", "document_refs", "documents"):
            value = suggestion.get(key)
            if value is None:
                value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        ids.append(str(item.get("document_id") or item.get("id") or "").strip())
                    else:
                        ids.append(str(item).strip())
            elif isinstance(value, dict):
                ids.append(str(value.get("document_id") or value.get("id") or "").strip())
            elif value:
                ids.append(str(value).strip())

        chunks = suggestion.get("evidence_chunks") or payload.get("evidence_chunks") or []
        if isinstance(chunks, list):
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                citation = chunk.get("citation") if isinstance(chunk.get("citation"), dict) else {}
                ids.append(str(chunk.get("document_id") or citation.get("document_id") or "").strip())
        return [item for item in ids if item]

    def _conflict_document_options(
        self,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[dict[str, str]]:
        options: list[dict[str, str]] = []

        def add_option(document_id: Any, label: Any = None) -> None:
            doc_id = str(document_id or "").strip()
            doc_label = str(label or "").strip()
            if doc_id:
                options.append({"id": doc_id, "label": doc_label or doc_id})

        add_option(
            suggestion.get("document_id") or payload.get("document_id"),
            suggestion.get("document_name")
            or suggestion.get("document_label")
            or payload.get("document_name")
            or payload.get("document_label"),
        )

        for key in ("documents", "document_refs", "citations"):
            value = suggestion.get(key)
            if value is None:
                value = payload.get(key)
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        add_option(
                            item.get("document_id") or item.get("id"),
                            item.get("document_name") or item.get("document_label") or item.get("name"),
                        )
            elif isinstance(value, dict):
                add_option(
                    value.get("document_id") or value.get("id"),
                    value.get("document_name") or value.get("document_label") or value.get("name"),
                )

        chunks = suggestion.get("evidence_chunks") or payload.get("evidence_chunks") or []
        if isinstance(chunks, list):
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                citation = chunk.get("citation") if isinstance(chunk.get("citation"), dict) else {}
                add_option(
                    chunk.get("document_id") or citation.get("document_id"),
                    chunk.get("document_name")
                    or chunk.get("document_label")
                    or citation.get("document_name")
                    or citation.get("document_label"),
                )
        return options

    def _dedupe_document_options(
        self,
        options: list[dict[str, str]],
        document_ids: list[str],
        document_labels: list[str],
    ) -> list[dict[str, str]]:
        result: list[dict[str, str]] = []
        labels_by_id: dict[str, str] = {}
        for index, document_id in enumerate(document_ids):
            label = document_labels[index] if index < len(document_labels) else document_id
            labels_by_id[document_id] = label or document_id

        for option in options:
            document_id = str(option.get("id") or "").strip()
            label = str(option.get("label") or "").strip()
            if document_id:
                labels_by_id[document_id] = label or labels_by_id.get(document_id) or document_id

        seen: set[str] = set()
        for document_id in document_ids + [option.get("id", "") for option in options]:
            document_id = str(document_id or "").strip()
            if not document_id or document_id in seen:
                continue
            seen.add(document_id)
            result.append({"id": document_id, "label": labels_by_id.get(document_id) or document_id})
        return result

    def _conflict_snippets(
        self,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
    ) -> list[str]:
        snippets: list[str] = []
        for key in ("snippet", "evidence_snippet", "citation_snippet"):
            value = suggestion.get(key)
            if value is None:
                value = payload.get(key)
            if value:
                snippets.append(str(value).strip())

        citations = suggestion.get("citations") or payload.get("citations") or []
        if isinstance(citations, list):
            for citation in citations:
                if isinstance(citation, dict):
                    snippets.append(str(citation.get("snippet") or "").strip())

        chunks = suggestion.get("evidence_chunks") or payload.get("evidence_chunks") or []
        if isinstance(chunks, list):
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                citation = chunk.get("citation") if isinstance(chunk.get("citation"), dict) else {}
                snippets.append(str(chunk.get("snippet") or citation.get("snippet") or "").strip())
        return [snippet for snippet in snippets if snippet]

    def _conflict_difference_category(
        self,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
        snippets: list[str],
    ) -> str:
        explicit = self._first_text(
            suggestion,
            payload,
            ("difference_category", "conflict_category", "category", "conflict_type", "type"),
        )
        if explicit:
            return explicit.replace("_", " ").replace("-", " ").strip().lower()
        text = " ".join(
            item
            for item in [
                self._first_text(
                    suggestion,
                    payload,
                    ("title", "summary", "conflict_signal", "conflict_hint", "message"),
                )
                or "",
                " ".join(snippets),
            ]
            if item
        ).lower()
        if any(token in text for token in ("varchar", "number", "decimal", "string", "integer", "type")):
            return "type difference"
        if any(token in text for token in ("nullable", "not null", "required", "optional")):
            return "nullable difference"
        if any(token in text for token in ("missing", "absent", "not found")):
            return "missing field in one source"
        if any(token in text for token in ("description", "semantic", "meaning", "business")):
            return "description/semantic difference"
        if any(token in text for token in ("name", "naming", "alias", "maps to", "mapped to")):
            return "naming difference"
        return "source alignment difference"

    def _conflict_normalized_mapping(
        self,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
    ) -> str | None:
        explicit = self._first_text(
            suggestion,
            payload,
            ("normalized_field_mapping", "field_mapping", "mapping", "canonical_mapping"),
        )
        if explicit:
            return explicit
        source = self._first_text(suggestion, payload, ("source_field", "legacy_field", "source_name"))
        target = self._first_text(suggestion, payload, ("target_field", "current_field", "canonical_field"))
        if source and target and source != target:
            return f"{source} -> {target}"
        return None

    def _conflict_delta_summary(
        self,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
        *,
        query: str,
        entity: str | None,
        field: str | None,
        difference_category: str,
        normalized_mapping: str | None,
        document_labels: list[str],
        snippets: list[str],
    ) -> str:
        explicit = self._first_text(
            suggestion,
            payload,
            ("delta_summary", "conflict_summary", "what_differs", "difference_summary"),
        )
        if explicit:
            return explicit
        signal = self._first_text(
            suggestion,
            payload,
            ("conflict_signal", "title", "summary", "conflict_hint", "message"),
        )
        if signal:
            return signal
        subject = ".".join(item for item in (entity, field) if item) or query or "This source item"
        if normalized_mapping:
            return f"{subject} appears with mapping {normalized_mapping}; review the preferred source before finalizing."
        if len(document_labels) >= 2:
            return f"{subject} differs between {document_labels[0]} and {document_labels[1]}; review the preferred source before finalizing."
        if snippets:
            return f"{subject} has a {difference_category}; review the cited source details before finalizing."
        return f"{subject} has a source alignment difference; review the preferred source before finalizing."

    def _evidence_citation_count(self, evidence_result: dict[str, Any]) -> int:
        chunks = evidence_result.get("evidence_chunks")
        if isinstance(chunks, list):
            return len(chunks)
        citations = evidence_result.get("citations")
        if isinstance(citations, list):
            return len(citations)
        return 0

    def _first_text(
        self,
        suggestion: dict[str, Any],
        payload: dict[str, Any],
        keys: tuple[str, ...],
    ) -> str | None:
        for key in keys:
            value = suggestion.get(key)
            if value is None:
                value = payload.get(key)
            text = str(value).strip() if value is not None else ""
            if text:
                return text
        return None

    def _coerce_confidence(self, value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _citation_count(self, suggestion: dict[str, Any], payload: dict[str, Any]) -> int:
        for key in ("citation_count", "source_count"):
            value = suggestion.get(key)
            if value is None:
                value = payload.get(key)
            if value is not None:
                try:
                    return int(value)
                except (TypeError, ValueError):
                    return 0
        citations = suggestion.get("citations") or payload.get("citations") or []
        if isinstance(citations, list):
            return len(citations)
        return 0

    def fetch_field_suggestions(
        self,
        session: ProjectSession,
        *,
        entity: str,
        min_source_count: int = 1,
        max_suggestions: int = 50,
    ) -> dict[str, Any] | None:
        if not self.is_enabled(session):
            return None

        try:
            workspace_id = ensure_workspace_identity(session)
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                catalog_result = client.read_field_catalog(
                    project_id=workspace_id,
                    entity=entity,
                )
                catalog_fields = catalog_result.get("fields", [])
                if not catalog_fields:
                    mark_workspace_active(session)
                    return {
                        "project_id": workspace_id,
                        "catalog_result": catalog_result,
                        "suggestion_result": None,
                    }

                suggestion_result = client.suggest_manifest_candidates(
                    project_id=workspace_id,
                    scope="fields",
                    entity=entity,
                    min_source_count=min_source_count,
                    max_suggestions=max_suggestions,
                )
                mark_workspace_active(session)
                return {
                    "project_id": workspace_id,
                    "catalog_result": catalog_result,
                    "suggestion_result": suggestion_result,
                }
        except (KSUnavailableError, KSCallError):
            return None

    def get_field_evidence_chain(
        self,
        session: ProjectSession,
        *,
        entity: str,
        field_name: str,
        suggestion_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.is_enabled(session):
            return None

        try:
            workspace_id = ensure_workspace_identity(session)
            resolved_suggestion_id = suggestion_id or _stable_field_suggestion_id(
                workspace_id,
                entity,
                field_name,
            )
            with ks_client(
                allowed_roots=workspace_allowed_roots(session),
                db_path=workspace_db_path(session),
            ) as client:
                result = client.get_suggestion_evidence_chain(
                    project_id=workspace_id,
                    scope="fields",
                    suggestion_id=resolved_suggestion_id,
                )
                mark_workspace_active(session)
                return result
        except (KSUnavailableError, KSCallError):
            return None


def _stable_field_suggestion_id(project_id: str, entity_name: str | None, field_name: str) -> str:
    normalized_entity = (entity_name or "").strip().lower()
    normalized_field_name = "".join(field_name.split()).lower()
    seed = f"field:{project_id}:{normalized_entity}:{normalized_field_name}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]
