"""Measured presentation contracts for the post-refresh visual polish pass."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.session_helpers import reset_session

ROOT = Path(__file__).resolve().parents[1]
CSS_PATH = ROOT / "app/static/css/studio.css"
BASE_PATH = ROOT / "app/templates/base.html"
FAVICON_PATH = ROOT / "app/static/favicon.svg"
DESIGN_SYSTEM_PATH = (
    ROOT
    / "docs/studio-ux-refresh/design-assets/design-system"
    / "edgeforge-studio-design-system.html"
)

client = TestClient(app)

DISCLOSURE = (
    "Use synthetic or approved content only. Studio does not sanitize uploaded or "
    "pasted content. Depending on the workflow, it may be retained in project state, "
    "Knowledge Workspace storage, and exported packages."
)


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _css() -> str:
    return CSS_PATH.read_text(encoding="utf-8")


def _root_tokens() -> dict[str, str]:
    root = re.search(r":root\s*\{(?P<body>.*?)\n\}", _css(), re.DOTALL)
    assert root
    return {
        name: value.strip()
        for name, value in re.findall(
            r"--([\w-]+)\s*:\s*([^;]+);", root.group("body")
        )
    }


def _rgb(hex_color: str) -> tuple[float, float, float]:
    value = hex_color.removeprefix("#")
    if len(value) == 3:
        value = "".join(channel * 2 for channel in value)
    assert len(value) == 6
    return tuple(int(value[index : index + 2], 16) / 255 for index in (0, 2, 4))


def _luminance(color: tuple[float, float, float]) -> float:
    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linear(channel) for channel in color)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast(foreground: str, background: str) -> float:
    light, dark = sorted((_luminance(_rgb(foreground)), _luminance(_rgb(background))), reverse=True)
    return (light + 0.05) / (dark + 0.05)


def _composite(foreground: str, background: str, alpha: float) -> str:
    foreground_rgb = _rgb(foreground)
    background_rgb = _rgb(background)
    channels = [
        round((front * alpha + back * (1 - alpha)) * 255)
        for front, back in zip(foreground_rgb, background_rgb, strict=True)
    ]
    return "#" + "".join(f"{channel:02x}" for channel in channels)


def _rule_blocks(source: str) -> list[tuple[str, str]]:
    return [
        (match.group("selector").strip(), match.group("body"))
        for match in re.finditer(
            r"(?P<selector>[^{}]+)\{(?P<body>[^{}]*)\}", source, re.DOTALL
        )
    ]


def test_ratified_chrome_tokens_and_locked_semantic_tokens_are_exact() -> None:
    tokens = _root_tokens()
    assert {
        name: tokens[name]
        for name in (
            "brand-navy",
            "rail-bg",
            "rail-line",
            "rail-ink",
            "rail-on-ink",
            "rail-bar",
            "rail-pill",
            "rail-island-bg",
            "rail-island-bg-strong",
            "rail-island-border",
            "rail-island-ink",
            "rail-island-control",
            "bg",
            "surface-muted",
            "workflow-group-bg",
            "workflow-group-border",
            "workflow-subsection-bg",
            "workflow-subsection-border",
            "workflow-row-bg",
            "workflow-row-alt-bg",
            "workflow-row-border",
            "workflow-detail-border",
            "border",
            "border-control",
            "shadow-sm",
            "shadow-md",
            "shadow-lg",
            "transition",
        )
    } == {
        "brand-navy": "#1e3a5f",
        "rail-bg": "linear-gradient(180deg, #24466b, var(--brand-navy))",
        "rail-line": "#2c5a86",
        "rail-ink": "#a9c0dd",
        "rail-on-ink": "#cfe2ff",
        "rail-bar": "#7db8ff",
        "rail-pill": "rgba(125, 184, 255, .16)",
        "rail-island-bg": "#9fc3e6",
        "rail-island-bg-strong": "#9fc3e6",
        "rail-island-border": "#5f84a8",
        "rail-island-ink": "#24466b",
        "rail-island-control": "#486b8d",
        "bg": "#edf1f6",
        "surface-muted": "#f4f7fa",
        "workflow-group-bg": "#dcecff",
        "workflow-group-border": "#a9bed2",
        "workflow-subsection-bg": "#eaf1f7",
        "workflow-subsection-border": "#c8d6e4",
        "workflow-row-bg": "#ffffff",
        "workflow-row-alt-bg": "#edf3f8",
        "workflow-row-border": "#ccd9e6",
        "workflow-detail-border": "#d4dde7",
        "border": "#dbe2ea",
        "border-control": "#74899f",
        "shadow-sm": "0 1px 3px rgba(10, 20, 40, .07)",
        "shadow-md": "0 10px 28px rgba(19, 39, 67, .16)",
        "shadow-lg": "0 20px 56px rgba(19, 39, 67, .22)",
        "transition": "130ms cubic-bezier(.2, .7, .3, 1)",
    }

    assert {name: tokens[name] for name in _LOCKED_SEMANTIC_TOKENS} == _LOCKED_SEMANTIC_TOKENS
    assert "sidebar-bg" not in tokens
    assert "sidebar-border" not in tokens


_LOCKED_SEMANTIC_TOKENS = {
    "success": "#16814a",
    "success-soft": "#ecfdf3",
    "warn": "#b7791f",
    "warn-soft": "#fff7e8",
    "danger": "#c0392b",
    "danger-soft": "#fff1ef",
    "ka-change-bg": "#fff3cf",
    "ka-change-border": "#d59b22",
    "ka-change-text": "#6f4100",
    "ka-satisfied-bg": "#f3f6fa",
    "ka-satisfied-border": "#b9c6d4",
    "ka-satisfied-text": "#4f6075",
    "ka-advisory-bg": "#eaf3fb",
    "ka-advisory-border": "#7fa6c8",
    "ka-advisory-text": "#24506f",
    "ka-evidence-bg": "#e6f6f4",
    "ka-evidence-border": "#3b9b90",
    "ka-evidence-text": "#125b55",
    "ka-attention-bg": "#fff0e8",
    "ka-attention-border": "#d56f43",
    "ka-attention-text": "#8a3316",
    "zone-scan": "#eaf0f8",
    "zone-editor": "#ffffff",
    "zone-derived": "#f3ecfd",
    "zone-derived-line": "#ddd0f2",
    "derived-ink": "#6d47c9",
    "zone-attn": "#fdf0d8",
    "zone-attn-line": "#eccf97",
    "zone-ready": "#e8f2f2",
    "fam-rest": "#0d9488",
    "fam-fixed": "#15803d",
    "fam-csv": "#4f46e5",
    "fam-xml": "#b45309",
    "fam-soap": "#1e3a5f",
    "fam-staging": "#475569",
}


def test_effective_rail_contrast_passes_at_both_gradient_endpoints() -> None:
    tokens = _root_tokens()
    endpoints = ("#24466b", tokens["brand-navy"])

    for endpoint in endpoints:
        assert _contrast(tokens["rail-ink"], endpoint) >= 4.5
        assert _contrast(tokens["rail-on-ink"], endpoint) >= 4.5
        assert _contrast("#ffffff", endpoint) >= 4.5
        assert _contrast(tokens["rail-bar"], endpoint) >= 3

        nav_background = _composite(tokens["rail-on-ink"], endpoint, 0.18)
        assert _contrast("#ffffff", nav_background) >= 4.5
        assert _contrast(tokens["rail-on-ink"], nav_background) >= 4.5
        rail_chip_background = _composite(
            tokens["rail-on-ink"], nav_background, 0.86
        )
        assert _contrast(tokens["brand-navy"], rail_chip_background) >= 4.5

        unavailable_background = _composite(tokens["rail-on-ink"], endpoint, 0.10)
        assert _contrast(tokens["rail-on-ink"], unavailable_background) >= 4.5

        active_background = _composite(tokens["rail-bar"], endpoint, 0.26)
        assert _contrast("#ffffff", active_background) >= 4.5
        assert _contrast(tokens["rail-on-ink"], active_background) >= 4.5

        selection_background = _composite("#2563eb", endpoint, 0.22)
        assert _contrast(tokens["rail-ink"], selection_background) >= 4.5
        assert _contrast(tokens["rail-on-ink"], selection_background) >= 4.5

    assert _contrast(tokens["brand-navy"], tokens["rail-bar"]) >= 4.5
    assert _contrast(tokens["brand-navy"], tokens["primary-soft"]) >= 4.5
    assert _contrast("#ffffff", tokens["primary"]) >= 4.5
    assert _contrast(tokens["success"], tokens["success-soft"]) >= 4.5
    assert _contrast("#96450a", tokens["warn-soft"]) >= 4.5

    for island_background in (
        tokens["rail-island-bg"],
        tokens["rail-island-bg-strong"],
    ):
        assert _contrast(tokens["text"], island_background) >= 4.5
        assert _contrast(tokens["rail-island-ink"], island_background) >= 4.5
        assert _contrast(tokens["rail-island-control"], island_background) >= 3
        assert _contrast("#0645ad", island_background) >= 4.5


def test_selection_inherits_contextual_text_and_marker_states_use_measured_ink() -> None:
    source = _css()
    selection = next(
        body for selector, body in _rule_blocks(source) if selector == "::selection"
    )
    assert "background: rgba(37, 99, 235, .22);" in selection
    assert not re.search(r"\bcolor\s*:", selection)

    active_marker = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == ".wizard-nav-link.is-active .wizard-nav-marker"
    )
    assert "color: var(--brand-navy);" in active_marker
    assert "background: var(--rail-bar);" in active_marker

    warning_marker = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == ".wizard-nav-link.is-warning .wizard-nav-marker"
    )
    assert "color: #96450a;" in warning_marker
    assert "background: var(--warn-soft);" in warning_marker


def test_canvas_control_cta_focus_disabled_and_scrollbar_contrast() -> None:
    tokens = _root_tokens()
    surfaces = (
        "#ffffff",
        tokens["bg"],
        tokens["surface-muted"],
        tokens["workflow-group-bg"],
        tokens["workflow-subsection-bg"],
        tokens["zone-scan"],
        tokens["zone-editor"],
        tokens["zone-derived"],
        tokens["zone-attn"],
        tokens["zone-ready"],
    )

    assert _contrast(tokens["muted-on-tint"], tokens["bg"]) >= 4.5
    assert _contrast(tokens["muted-on-tint"], tokens["workflow-group-bg"]) >= 4.5
    for surface in surfaces:
        assert _contrast(tokens["border-control"], surface) >= 3
        assert _contrast(tokens["primary"], surface) >= 3

    assert _contrast("#ffffff", "#2563eb") >= 4.5
    assert _contrast("#ffffff", "#1d4ed8") >= 4.5
    assert _contrast(tokens["muted"], tokens["surface-muted"]) >= 4.5
    assert _contrast(tokens["border-control"], tokens["surface-muted"]) >= 3

    for track in (tokens["surface"], "#10233f", "#0f172a"):
        assert _contrast(tokens["border-control"], track) >= 3


def test_shell_uses_dedicated_brand_chrome_without_opacity_or_family_aliases() -> None:
    source = _css()
    shell_markers = (".app-shell", ".shell-", ".sidebar-", ".wizard-nav")
    shell_blocks = [
        (selector, body)
        for selector, body in _rule_blocks(source)
        if any(marker in selector for marker in shell_markers)
    ]

    assert shell_blocks
    assert all("--fam-soap" not in body for _, body in shell_blocks)
    rail_text_markers = (".sidebar-", ".wizard-nav", ".uxr-rail-chip")
    rail_text_blocks = [
        (selector, body)
        for selector, body in _rule_blocks(source)
        if any(marker in selector for marker in rail_text_markers)
    ]
    assert all(not re.search(r"\bopacity\s*:", body) for _, body in rail_text_blocks)

    assert "background: var(--rail-bg);" in source
    assert "linear-gradient(90deg, #24466b, var(--brand-navy))" in source
    assert "box-shadow: inset 3px 0 0 var(--rail-bar)" in source
    assert "outline-color: var(--rail-bar);" in source


def test_controls_elevation_and_micro_system_are_scoped_to_existing_surfaces() -> None:
    source = _css()

    assert "input[type=search]," in source
    assert source.count("border: 1px solid var(--border-control);") >= 1
    assert "body.ux-refresh .uxr-board-edit-btn" in source
    assert "background: linear-gradient(180deg, #2563eb, #1d4ed8);" in source
    assert ".btn-primary:disabled" in source

    for selector in (
        ".kickoff-workspace-panel",
        ".step-section-card",
        ".card",
        ".knowledge-header",
        ".knowledge-panel",
    ):
        block = next(body for current, body in _rule_blocks(source) if current == selector)
        assert "box-shadow: var(--shadow-sm);" in block

    assert "[data-uxr-focus-editor]" in source
    assert ".ka-suggestion-drawer-panel" in source
    assert 'body[data-shell-drawer="expanded"] .shell-bottom-drawer' in source
    assert source.count("box-shadow: var(--shadow-lg);") == 2
    assert "accent-color: var(--primary);" in source
    assert "font-variant-numeric: tabular-nums;" in source
    assert "::selection" in source
    assert "summary::after" in source
    assert "content: '+'" not in source
    assert "content: '−'" not in source


def test_surface_hierarchy_is_explicit_across_every_refreshed_workflow() -> None:
    templates = (
        "step1_project.html",
        "step2_upstream.html",
        "step3_entities.html",
        "step3_passthrough.html",
        "step4_handoffs.html",
        "step5_downstream.html",
        "step6_rules.html",
        "step7_review.html",
        "step8_export.html",
        "kafka_step1_topics.html",
        "kafka_step2_routes.html",
        "kafka_step3_transforms.html",
        "knowledge_workspace.html",
    )
    for template in templates:
        source = (ROOT / "app/templates" / template).read_text(encoding="utf-8")
        assert "workflow-surface-group" in source, template
        assert "workflow-surface-card" in source, template
        assert any(
            marker in source
            for marker in ("workflow-surface-detail", "workflow-surface-subsection")
        ), template

    source = _css()
    assert ".workflow-surface-group .card" not in source
    assert ".workflow-surface-card .workflow-surface-card" not in source
    assert "body.ux-refresh .workflow-surface-group > .kickoff-header" in source
    assert "body.ux-refresh .review-step-surface > .tracelens" in source


def test_reported_nested_workflows_use_distinct_depth_and_record_classes() -> None:
    kafka_topics = (ROOT / "app/templates/kafka_step1_topics.html").read_text(
        encoding="utf-8"
    )
    kafka_routes = (ROOT / "app/templates/kafka_step2_routes.html").read_text(
        encoding="utf-8"
    )
    kafka_transforms = (
        ROOT / "app/templates/kafka_step3_transforms.html"
    ).read_text(encoding="utf-8")
    step3_js = (ROOT / "app/static/js/step3_entities.js").read_text(
        encoding="utf-8"
    )
    step8 = (ROOT / "app/templates/step8_export.html").read_text(
        encoding="utf-8"
    )
    css = _css()

    assert 'kafka-topic-card workflow-surface-subsection' in kafka_topics
    assert 'disclosure-card workflow-surface-row' in kafka_topics
    assert 'disclosure-card workflow-surface-subsection' in kafka_routes
    assert 'router-upstream-row step-section-card workflow-surface-row' in kafka_routes
    assert 'router-target-transform-card step-section-card workflow-surface-subsection' in kafka_transforms
    assert 'disclosure-card workflow-surface-row' in kafka_transforms
    assert 'router-transform-row ${rowClass} step-section-card workflow-surface-detail' in kafka_transforms
    assert "phase2-interface-panel workflow-surface-subsection" in step3_js
    assert 'phase2-operation workflow-surface-row' in step3_js
    assert 'phase2-mappings workflow-surface-detail' in step3_js
    assert 's8-box workflow-surface-card' in step8
    assert 's8-surface-card workflow-surface-subsection' in step8
    assert 's8-artifact-row workflow-surface-row' in step8
    assert 'body.ux-refresh .uxr-focus-split-editor' in css
    assert 'body.ux-refresh [data-uxr-focus-editor]' in css
    assert 'body.ux-refresh .drawer-table-shell .review-history-row:nth-child(even) > td' in css


def test_nested_workflow_rows_are_uniform_and_phase2_content_is_inset() -> None:
    css = _css()
    step3_js = (ROOT / "app/static/js/step3_entities.js").read_text(
        encoding="utf-8"
    )
    step5 = (ROOT / "app/templates/step5_downstream.html").read_text(
        encoding="utf-8"
    )

    assert ".workflow-row-list > .workflow-surface-row:nth-child(even)" not in css
    assert (
        "body.ux-refresh .drawer-table-shell .review-history-row:nth-child(even) > td"
        in css
    )

    phase2 = next(
        body
        for selector, body in _rule_blocks(css)
        if selector == "body.ux-refresh .phase2-surface"
    )
    assert "padding-inline: 20px;" in phase2
    assert "padding-bottom: 20px;" in phase2

    entity_panel = next(
        body
        for selector, body in _rule_blocks(css)
        if selector == "body.ux-refresh .phase2-interface-panel"
    )
    assert "background: var(--surface-strong);" in entity_panel
    assert "border-color: var(--workflow-group-border);" in entity_panel
    assert '<details class="phase2-operation workflow-surface-row" open' not in step3_js

    assert "workflow-surface-group saved-file-specs" in step5
    saved_spec_row = next(
        body
        for selector, body in _rule_blocks(css)
        if selector == "body.ux-refresh .saved-file-specs .review-row-card"
    )
    assert "padding: 16px 18px;" in saved_spec_row
    saved_spec_layout = next(
        body
        for selector, body in _rule_blocks(css)
        if selector == "body.ux-refresh .saved-file-specs .review-row-main"
        and "grid-template-columns: minmax(180px" in body
    )
    assert "gap: 18px;" in saved_spec_layout


def test_board_rows_have_measured_hover_and_keyboard_focus_feedback() -> None:
    source = _css()
    row = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == "body.ux-refresh .uxr-board-row"
    )
    assert "background var(--transition)" in row
    assert "border-color var(--transition)" in row
    assert "box-shadow var(--transition)" in row
    assert "transform var(--transition)" in row

    interactive = next(
        body
        for selector, body in _rule_blocks(source)
        if "body.ux-refresh .uxr-board-row:hover" in selector
        and "body.ux-refresh .uxr-board-row:focus-within" in selector
    )
    assert "border-color: var(--primary);" in interactive
    assert "box-shadow: inset 3px 0 0 var(--primary), var(--shadow-sm);" in interactive
    assert "transform: translateX(2px);" in interactive
    assert "background:" not in interactive


def test_motion_contract_has_no_implicit_or_layout_property_transitions() -> None:
    source = _css()
    transitions = re.findall(r"\btransition\s*:\s*([^;]+);", source)

    assert transitions
    for transition in transitions:
        assert transition.strip() != "var(--transition)"
        assert not re.search(r"(^|,)\s*all(?:\s|$)", transition)
        assert "grid-template-columns" not in transition
        assert "max-width" not in transition
        assert "max-height" not in transition
        assert "filter" not in transition

    assert "@view-transition" in source
    assert "view-transition-name: step-marker;" in source
    assert "animation-duration: 160ms;" in source
    assert "animation: uxr-focus-editor-enter 220ms" in source
    assert "translateY(4px)" in source
    assert "animation: ka-suggestion-drawer-enter 200ms" in source
    drawer_keyframes = re.search(
        r"@keyframes ka-suggestion-drawer-enter\s*\{(?P<body>.*?)\n\}",
        source,
        re.DOTALL,
    )
    assert drawer_keyframes
    assert "opacity: 0;" in drawer_keyframes.group("body")
    assert "translateX(6px)" in drawer_keyframes.group("body")
    assert "opacity: 1;" in drawer_keyframes.group("body")
    assert "translateX(0)" in drawer_keyframes.group("body")
    assert "animation-timeline: scroll(root block);" in source
    scroll_keyframes = re.search(
        r"@keyframes shell-header-shadow-in\s*\{(?P<body>.*?)\n\}",
        source,
        re.DOTALL,
    )
    assert scroll_keyframes
    assert "opacity" in scroll_keyframes.group("body")
    assert "box-shadow" not in scroll_keyframes.group("body")

    reduced = source[source.index("@media (prefers-reduced-motion: reduce)") :]
    for expected in (
        "navigation: none",
        "animation: none !important",
        "animation-duration: .01ms !important",
        "animation-delay: 0s !important",
        "animation-iteration-count: 1 !important",
        "transition-duration: .01ms !important",
        "transition-delay: 0s !important",
        "scroll-behavior: auto !important",
    ):
        assert expected in reduced


def test_internal_scrollbars_are_explicit_and_page_scrollbar_is_untouched() -> None:
    source = _css()
    assert "scrollbar-width: thin" not in source
    assert "scrollbar-color: var(--border-control) var(--scrollbar-track);" in source
    assert "scrollbar-gutter: stable;" in source
    assert "width: 8px;" in source
    assert "height: 8px;" in source
    assert "pre::-webkit-scrollbar" in source
    assert ".s8-log::-webkit-scrollbar" in source
    assert ".ka-suggestion-drawer-body::-webkit-scrollbar" in source
    assert ".shell-bottom-drawer .shell-drawer-panel.active::-webkit-scrollbar" in source
    assert ".shell-sidebar::-webkit-scrollbar" in source
    assert not re.search(r"(?:^|,)\s*(?:html|body)::-webkit-scrollbar", source)


def test_desktop_sidebar_scrolls_to_project_file_at_constrained_heights() -> None:
    source = _css()
    sidebar = next(
        body for selector, body in _rule_blocks(source) if selector == ".shell-sidebar"
    )

    assert "height: 100vh;" in sidebar
    assert "overflow-y: auto;" in sidebar
    assert "overscroll-behavior-y: contain;" in sidebar
    assert "scrollbar-color: var(--rail-bar) var(--brand-navy);" in sidebar
    assert "scrollbar-gutter: stable;" in sidebar

    responsive_sidebar_blocks = [
        body
        for selector, body in _rule_blocks(source)
        if selector == ".shell-sidebar" and "overflow-y: visible;" in body
    ]
    assert responsive_sidebar_blocks
    assert "scrollbar-gutter: auto;" in responsive_sidebar_blocks[0]


def test_shell_renders_one_named_active_marker_and_local_favicon() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert '<link rel="icon" href="/static/favicon.svg">' in response.text
    assert response.text.count("wizard-nav-marker is-step-marker") == 1
    assert "Governed authoring workspace" in response.text
    assert "Studio v2 frame" not in response.text
    assert '<span class="wizard-nav-label">Downstream Contract</span>' in response.text

    downstream = client.get("/downstream")
    assert downstream.status_code == 200
    assert "Step 5: Downstream Interfaces" in downstream.text
    assert '<span class="wizard-nav-label">Downstream Contract</span>' in downstream.text

    favicon = FAVICON_PATH.read_text(encoding="utf-8")
    assert favicon.startswith("<svg ")
    root = ET.fromstring(favicon)
    assert root.tag.rsplit("}", 1)[-1] == "svg"
    for element in root.iter():
        assert element.tag.rsplit("}", 1)[-1] in {"svg", "path"}
        for name, value in element.attrib.items():
            local_name = name.rsplit("}", 1)[-1].lower()
            assert not local_name.startswith("on")
            assert local_name not in {"href", "src", "style"}
            assert "javascript:" not in value.lower()
            assert "url(" not in value.lower()

    assert "<script" not in favicon.lower()
    assert "@font-face" not in favicon


def test_rendered_rail_project_utility_uses_blue_island_controls() -> None:
    response = client.get("/")
    assert response.status_code == 200
    source = _css()
    scoped_rule = re.search(
        r"\.shell-sidebar \.sidebar-file-btn\s*\{(?P<body>.*?)\}",
        source,
        re.DOTALL,
    )
    assert scoped_rule
    declarations = scoped_rule.group("body")
    assert "border-color: var(--rail-island-control);" in declarations
    assert "background: var(--surface-muted);" in declarations
    assert "color: var(--text);" in declarations

    project_card = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == ".sidebar-project-file"
    )
    assert "background: var(--rail-island-bg);" in project_card
    assert "border: 1px solid var(--rail-island-border);" in project_card
    assert "box-shadow: var(--shadow-sm);" in project_card
    assert "height: 128px;" in project_card
    assert "display: block;" in project_card


def test_data_handling_disclosure_is_contextual_and_native() -> None:
    source = BASE_PATH.read_text(encoding="utf-8")
    sidebar_start = source.index('<div class="sidebar-project-file">')
    sidebar_end = source.index("</aside>", sidebar_start)
    sidebar = source[sidebar_start:sidebar_end]
    header_start = source.index('<div class="shell-header-meta">')
    header_end = source.index("</header>", header_start)
    header = source[header_start:header_end]
    normalized_header = re.sub(r"\s+", " ", header)

    assert DISCLOSURE not in re.sub(r"\s+", " ", sidebar)
    assert "sidebar-data-handling-notice" not in source
    assert '<details class="shell-data-handling">' in header
    assert '<summary class="shell-pill shell-data-handling-toggle">Data handling</summary>' in header
    assert 'id="studio-data-handling-note"' in header
    assert 'role="note"' in header
    assert DISCLOSURE in normalized_header
    assert sidebar.count('aria-describedby="studio-data-handling-note"') == 2
    assert "<script" not in header
    assert source.count('<script src="/static/js/studio.js"></script>') == 1


def test_data_handling_panel_is_bounded_without_sidebar_override() -> None:
    source = _css()
    panel = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == ".shell-data-handling-panel"
    )

    assert "position: absolute;" in panel
    assert "width: min(380px, calc(100vw - 48px));" in panel
    assert "max-height: min(50vh, 300px);" in panel
    assert "overflow: auto;" in panel
    assert ".sidebar-project-file .data-handling-notice" not in source


def test_shell_header_and_rail_islands_are_deeper_than_workflow_canvas() -> None:
    source = _css()
    tokens = _root_tokens()

    assert tokens["rail-island-bg"] == tokens["rail-island-bg-strong"]
    assert tokens["rail-island-bg"] != tokens["workflow-group-bg"]
    assert tokens["workflow-group-bg"] == "#dcecff"
    assert _luminance(_rgb(tokens["rail-island-bg"])) < _luminance(
        _rgb(tokens["workflow-group-bg"])
    )

    header = next(
        body for selector, body in _rule_blocks(source) if selector == ".shell-header"
    )
    assert "background: var(--rail-island-bg);" in header
    assert "border-bottom: 1px solid var(--rail-island-border);" in header
    assert "backdrop-filter" not in header

    brand = next(
        body for selector, body in _rule_blocks(source) if selector == ".sidebar-brand"
    )
    assert "background: var(--rail-island-bg);" in brand
    assert "linear-gradient" not in brand
    assert "height: 128px;" in brand

    step_indicator = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == ".shell-step-indicator"
    )
    assert "background: var(--workflow-subsection-bg);" in step_indicator
    assert "border-color: var(--workflow-subsection-border);" in step_indicator

    nav_link = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == ".wizard-nav-link"
    )
    assert "height: 60px;" in nav_link
    assert "min-height: 60px;" in nav_link
    assert "justify-content: flex-start;" in nav_link
    assert "gap: 14px;" in nav_link
    assert "padding: 6px 10px;" in nav_link
    assert "background: rgba(207, 226, 255, .18);" in nav_link
    assert "border: 1px solid rgba(207, 226, 255, .48);" in nav_link
    assert "color: #ffffff;" in nav_link
    assert "transform var(--transition)" in nav_link

    nav_hover = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == ".wizard-nav-link:hover"
    )
    assert "background: rgba(207, 226, 255, .24);" in nav_hover
    assert "transform: translateX(2px);" in nav_hover

    active_nav = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == ".wizard-nav-link.is-active"
    )
    assert "background: rgba(125, 184, 255, .26);" in active_nav
    assert "inset 3px 0 0 var(--rail-bar)" in active_nav

    nav_copy = next(
        body
        for selector, body in _rule_blocks(source)
        if selector == ".wizard-nav-copy"
    )
    assert "align-self: stretch;" in nav_copy
    assert "display: flex;" in nav_copy
    assert "flex: 1;" in nav_copy
    assert "align-items: flex-start;" in nav_copy
    assert "justify-content: center;" in nav_copy
    assert "text-align: left;" in nav_copy

    nav = next(
        body for selector, body in _rule_blocks(source) if selector == ".wizard-nav"
    )
    assert "gap: 12px;" in nav

    rail_chip = next(
        body
        for selector, body in reversed(_rule_blocks(source))
        if selector == "body.ux-refresh .uxr-rail-chip"
    )
    assert "align-self: flex-start;" in rail_chip
    assert "background: rgba(207, 226, 255, .86);" in rail_chip
    assert "color: var(--brand-navy);" in rail_chip
    assert "font-size: 9px;" in rail_chip
    assert "line-height: 11px;" in rail_chip
    assert "padding: 1px 6px;" in rail_chip

    compact_rail = source[
        source.index("@media (max-width: 1024px)") : source.index(
            "@media (max-width: 900px)"
        )
    ]
    assert "height: 46px;" in compact_rail
    assert "min-height: 46px;" in compact_rail

    responsive_start = source.index("@media (max-width: 900px)")
    responsive_rail = source[
        responsive_start : source.index("@media (max-width: 760px)", responsive_start)
    ]
    assert "height: 60px;" in responsive_rail
    assert "min-height: 60px;" in responsive_rail


def test_reduced_motion_keeps_busy_indicators_and_adjacent_status_text() -> None:
    source = _css()
    step2 = (ROOT / "app/templates/step2_upstream.html").read_text(encoding="utf-8")
    step8 = (ROOT / "app/templates/step8_export.html").read_text(encoding="utf-8")

    assert ".spinner" in source
    assert "display: inline-block;" in source
    assert "display: none" not in source[source.index("@media (prefers-reduced-motion: reduce)") :]
    assert 'id="url-spinner" class="spinner hidden"' in step2
    assert "Fetch &amp; Classify" in step2
    assert 'id="run-all-spinner" class="spinner hidden"' in step8
    assert "Export &amp; Validate" in step8


def test_design_system_preserves_history_and_records_finding_d_supersession() -> None:
    source = DESIGN_SYSTEM_PATH.read_text(encoding="utf-8")
    assert "Mockup neutrals ≠ shipped neutrals" in source
    assert "Superseded by the post-refresh measured polish pass" in source
    assert "Locked zone, family, status, and KA tokens remain unchanged" in source
