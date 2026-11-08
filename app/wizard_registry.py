"""Registry-backed wizard step metadata."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WizardStep:
    step_id: str
    archetype: str
    label: str
    route: str | None
    suggestion_scope: str
    position: int
    applicable: bool = True


ARCHETYPE_LABELS: dict[str, str] = {
    "crud": "CRUD",
    "passthrough-router": "Passthrough Router",
    "kafka-integration": "Kafka Integration",
}


STEP_REGISTRY: dict[str, list[WizardStep]] = {
    "crud": [
        WizardStep("project-setup", "shared", "Project Setup", "/", "none", 1),
        WizardStep("upstream-ingest", "crud", "Upstream Contract", "/upstream", "none", 2),
        WizardStep("entity-model", "crud", "Entity Model", "/entities", "entity-fields", 3),
        WizardStep("data-handoffs", "crud", "Data Handoffs", "/handoffs", "none", 4),
        WizardStep(
            "downstream-interfaces",
            "crud",
            "Downstream Contract",
            "/downstream",
            "none",
            5,
        ),
        WizardStep("rules-mappings", "shared", "Rules & Mappings", "/rules", "rules", 6),
        WizardStep("review", "shared", "Review", "/review", "none", 7),
        WizardStep("export-build-run", "shared", "Export & Build", "/export", "none", 8),
    ],
    "kafka-integration": [
        WizardStep("project-setup", "shared", "Project Setup", "/", "none", 1),
        WizardStep(
            "kafka-topic-ingest",
            "kafka-integration",
            "Topic Ingest",
            "/kafka/topics",
            "none",
            2,
        ),
        WizardStep(
            "kafka-route-model",
            "kafka-integration",
            "Route Model",
            "/kafka/routes",
            "route-config",
            3,
        ),
        WizardStep(
            "kafka-transform-mappings",
            "kafka-integration",
            "Transform Mappings",
            "/kafka/transforms",
            "transform-mappings",
            4,
        ),
        WizardStep(
            "downstream-interfaces",
            "kafka-integration",
            "Downstream Contract",
            None,
            "none",
            5,
            applicable=False,
        ),
        WizardStep("rules-mappings", "shared", "Rules & Mappings", "/rules", "rules", 6),
        WizardStep("review", "shared", "Review", "/review", "none", 7),
        WizardStep("export-build-run", "shared", "Export & Build", "/export", "none", 8),
    ],
    "passthrough-router": [
        WizardStep("project-setup", "shared", "Project Setup", "/", "none", 1),
        WizardStep(
            "passthrough-upstream",
            "passthrough-router",
            "Upstream Contract",
            "/upstream",
            "none",
            2,
        ),
        WizardStep(
            "passthrough-route",
            "passthrough-router",
            "Route & Transform",
            "/passthrough",
            "route-config",
            3,
        ),
        WizardStep(
            "data-handoffs",
            "passthrough-router",
            "Data Handoffs",
            None,
            "none",
            4,
            applicable=False,
        ),
        WizardStep(
            "downstream-interfaces",
            "passthrough-router",
            "Downstream Contract",
            None,
            "none",
            5,
            applicable=False,
        ),
        WizardStep("rules-mappings", "shared", "Rules & Mappings", "/rules", "rules", 6),
        WizardStep("review", "shared", "Review", "/review", "none", 7),
        WizardStep("export-build-run", "shared", "Export & Build", "/export", "none", 8),
    ],
}


def get_steps(archetype: str) -> list[WizardStep]:
    return STEP_REGISTRY.get(archetype, STEP_REGISTRY["crud"])


def get_archetype_label(archetype: str) -> str:
    return ARCHETYPE_LABELS.get(archetype, ARCHETYPE_LABELS["crud"])
