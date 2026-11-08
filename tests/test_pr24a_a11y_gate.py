"""Final UX-refresh accessibility gate for Steps 2 through 7.

The fixtures deliberately contain represented items. Empty projects omit board
scaffolding by design, so they cannot prove the board, filter, state-label, and
focus contracts that PR-24a must keep durable before the default-on flip.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.session_helpers import reset_session
from tests.test_step2_save_one import _session_with_interfaces
from tests.test_step3_identity_role_lens import _seed_lens
from tests.test_step4_triage_board import (
    _triage_board_session as _step4_triage_board_session,
)
from tests.test_step5_triage_board import (
    _triage_board_session as _step5_triage_board_session,
)
from tests.test_step6_save_one import _seed_rules_session
from tests.test_step7_trace_lens import _trace_lens_session

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)
STATE_LABELS = {"Ready", "Draft", "Blocked", "Needs action", "Review"}
VOID_ELEMENTS = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _MarkupProbe(HTMLParser):
    """Collect rendered elements and their descendant text without a DOM dependency."""

    def __init__(self, markup: str) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[dict[str, object]] = []
        self._stack: list[dict[str, object]] = []
        self.feed(markup)

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        node: dict[str, object] = {
            "tag": tag,
            "attrs": {name: value or "" for name, value in attrs},
            "text": "",
        }
        self.nodes.append(node)
        if tag not in VOID_ELEMENTS:
            self._stack.append(node)

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        self.handle_starttag(tag, attrs)
        if self._stack and self._stack[-1]["tag"] == tag:
            self._stack.pop()

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        for node in self._stack:
            node["text"] = f"{node['text']}{data}"

    def find_all(
        self,
        *,
        tag: str | None = None,
        class_name: str | None = None,
        **attrs: str,
    ) -> list[dict[str, object]]:
        matches = []
        for node in self.nodes:
            node_attrs = node["attrs"]
            assert isinstance(node_attrs, dict)
            if tag and node["tag"] != tag:
                continue
            if class_name and class_name not in str(node_attrs.get("class", "")).split():
                continue
            if any(node_attrs.get(name) != value for name, value in attrs.items()):
                continue
            matches.append(node)
        return matches


@pytest.fixture(autouse=True)
def _clean_session() -> Iterator[None]:
    reset_session()
    yield
    reset_session()


def _render(
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    *,
    split: bool = False,
) -> str:
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "true")
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_SPLIT", "true" if split else "false")
    response = client.get(route)
    assert response.status_code == 200
    return response.text


def _attrs(node: dict[str, object]) -> dict[str, str]:
    attrs = node["attrs"]
    assert isinstance(attrs, dict)
    return attrs


def _text(node: dict[str, object]) -> str:
    return " ".join(str(node["text"]).split())


@pytest.mark.parametrize(
    ("route", "board_key", "seed"),
    (
        ("/upstream", "upstream", _session_with_interfaces),
        ("/handoffs", "handoffs", _step4_triage_board_session),
        ("/downstream", "downstream", _step5_triage_board_session),
        ("/rules", "rules", _seed_rules_session),
    ),
)
def test_board_surfaces_expose_labels_filters_and_text_verdicts(
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    board_key: str,
    seed: Callable[[], object],
) -> None:
    seed()
    markup = _render(monkeypatch, route)
    probe = _MarkupProbe(markup)

    boards = probe.find_all(
        role="region",
        **{"data-uxr-board": board_key},
    )
    assert len(boards) == 1
    assert _attrs(boards[0]).get("aria-label", "").strip()

    filter_groups = probe.find_all(
        class_name="uxr-board-filters",
        role="group",
    )
    assert filter_groups
    assert all(_attrs(group).get("aria-label", "").strip() for group in filter_groups)

    chips = [
        node
        for node in probe.find_all(tag="button", class_name="uxr-chip")
        if _attrs(node).get("aria-pressed") in {"true", "false"}
    ]
    assert chips
    assert all(_text(chip) for chip in chips)

    verdicts = {
        _text(node)
        for node in probe.find_all(class_name="badge")
        if _text(node) in STATE_LABELS
    }
    assert verdicts, "a seeded readiness state must have a visible text verdict"

    for tile in probe.find_all(class_name="uxr-fam-tile"):
        assert _text(tile)
        attrs = _attrs(tile)
        assert (
            attrs.get("aria-label", "").strip()
            or attrs.get("aria-hidden") == "true"
        )

    if board_key == "rules":
        assert "SPEC-DERIVED" in markup
        assert "MANUAL" in markup


@pytest.mark.parametrize(
    ("route", "seed", "status_id"),
    (
        ("/upstream", _session_with_interfaces, "edge-contract-status"),
        ("/handoffs?focus=ready-one", _step4_triage_board_session, "save-status"),
        ("/downstream?focus=fixed-ready", _step5_triage_board_session, "save-status"),
        ("/rules?focus=Account", _seed_rules_session, "save-status"),
    ),
)
def test_save_surfaces_expose_a_polite_live_status(
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    seed: Callable[[], object],
    status_id: str,
) -> None:
    seed()
    probe = _MarkupProbe(_render(monkeypatch, route))

    statuses = probe.find_all(
        tag="div",
        id=status_id,
        role="status",
        **{"aria-live": "polite"},
    )
    assert len(statuses) == 1


def test_step5_board_and_focus_expose_native_open_and_live_review_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _step5_triage_board_session()
    board_probe = _MarkupProbe(_render(monkeypatch, "/downstream"))

    rows = board_probe.find_all(class_name="uxr-board-row")
    edit_links = board_probe.find_all(tag="a", class_name="uxr-board-edit-btn")
    assert rows
    assert len(edit_links) == len(rows)
    assert all(
        _attrs(link).get("href", "").startswith("/downstream?focus=")
        and _text(link) == "Edit"
        for link in edit_links
    )

    focus_probe = _MarkupProbe(_render(monkeypatch, "/downstream?focus=fixed-ready"))
    assert len(
        focus_probe.find_all(
            **{"data-uxr-tab-badges": "", "aria-live": "polite"},
        )
    ) == 1
    assert len(
        focus_probe.find_all(
            role="alert",
            **{"data-uxr-conflict-review": "", "aria-live": "assertive"},
        )
    ) == 1


def test_entities_and_review_have_labelled_sections_and_save_live_regions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_lens(roles={"accountId": "persistence_id"})
    entity_probe = _MarkupProbe(_render(monkeypatch, "/entities"))
    assert entity_probe.find_all(**{"aria-label": "Identity role summary"})
    assert entity_probe.find_all(**{"aria-label": "Entities"})
    for status_id in ("save-status", "phase2-status"):
        assert len(
            entity_probe.find_all(
                id=status_id,
                role="status",
                **{"aria-live": "polite"},
            )
        ) == 1

    _trace_lens_session()
    review_probe = _MarkupProbe(_render(monkeypatch, "/review"))
    trace_lens = review_probe.find_all(**{"data-trace-lens": ""})
    assert len(trace_lens) == 1
    assert _attrs(trace_lens[0]).get("aria-label", "").strip()
    assert len(
        review_probe.find_all(
            id="review-posture-status",
            role="status",
            **{"aria-live": "polite"},
        )
    ) == 1


@pytest.mark.parametrize(
    ("route", "seed", "status_ids"),
    (
        ("/upstream", _session_with_interfaces, ("edge-contract-status",)),
        (
            "/entities",
            _seed_lens,
            ("save-status", "phase2-status"),
        ),
        ("/review", _trace_lens_session, ("review-posture-status",)),
    ),
)
def test_shared_save_regions_announce_even_with_retired_flag_set_false(
    monkeypatch: pytest.MonkeyPatch,
    route: str,
    seed: Callable[[], object],
    status_ids: tuple[str, ...],
) -> None:
    seed()
    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    response = client.get(route)
    assert response.status_code == 200
    probe = _MarkupProbe(response.text)

    for status_id in status_ids:
        statuses = probe.find_all(id=status_id)
        assert len(statuses) == 1
        assert _attrs(statuses[0]).get("role") == "status"
        assert _attrs(statuses[0]).get("aria-live") == "polite"


def test_step5_split_focus_keeps_the_same_labelled_live_editor_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _step5_triage_board_session()
    probe = _MarkupProbe(
        _render(
            monkeypatch,
            "/downstream?focus=fixed-ready",
            split=True,
        )
    )

    assert len(probe.find_all(**{"data-uxr-split": "true"})) == 1
    focus_editors = probe.find_all(
        role="region",
        **{"data-uxr-focus-editor": "fixed-ready"},
    )
    assert len(focus_editors) == 1
    focus_label = _attrs(focus_editors[0]).get("aria-labelledby", "")
    assert focus_label
    assert probe.find_all(id=focus_label)
    assert len(
        probe.find_all(
            id="save-status",
            role="status",
            **{"aria-live": "polite"},
        )
    ) == 1
    assert len(
        probe.find_all(
            **{"data-uxr-tab-badges": "", "aria-live": "polite"},
        )
    ) == 1
    assert len(
        probe.find_all(
            role="alert",
            **{"data-uxr-conflict-review": "", "aria-live": "assertive"},
        )
    ) == 1


def test_static_focus_contrast_and_narrow_fallback_contracts_remain_locked() -> None:
    css = (ROOT / "app/static/css/studio.css").read_text()

    assert re.search(r":focus-visible[^{]*\{[^}]*\boutline\s*:", css, re.DOTALL)
    assert "--muted-on-tint: #546580;" in css
    assert "--fam-rest: #0d9488;" in css
    assert (
        "body.ux-refresh .uxr-fam-tile.uxr-fam-rest "
        "{ background: #0b8277; }"
    ) in css
    assert "color: #0f6a32;" in css
    assert "color: #96450a;" in css
    assert "color: #4f6075;" in css

    assert "body.ux-refresh .uxr-focus-split-board {\n  display: none;" in css
    assert "@media (min-width: 1200px)" in css
    assert (
        "body.ux-refresh .uxr-focus-split-board {\n"
        "    display: block;"
    ) in css


def test_walkthrough_image_extensions_match_their_content() -> None:
    image_dir = ROOT / "docs/studio-ux-refresh/pr24a-a11y-walkthrough-images"
    expected_signatures = {
        ".jpg": b"\xff\xd8\xff",
        ".png": b"\x89PNG\r\n\x1a\n",
    }

    images = [
        path
        for path in image_dir.iterdir()
        if path.suffix.lower() in expected_signatures
    ]
    assert images
    for image in images:
        assert image.read_bytes().startswith(expected_signatures[image.suffix.lower()])


def test_dirty_guard_and_board_keyboard_contracts_remain_durable() -> None:
    studio_js = (ROOT / "app/static/js/studio.js").read_text()
    assert "function createDirtyTracker({ snapshot })" in studio_js
    assert "window.addEventListener('beforeunload', beforeUnload)" in studio_js
    assert "'a[href], [data-dirty-navigation]'" in studio_js

    for template_name in (
        "step2_upstream.html",
        "step4_handoffs.html",
        "step5_downstream.html",
        "step6_rules.html",
    ):
        source = (ROOT / f"app/templates/{template_name}").read_text()
        assert "['ArrowDown', 'ArrowUp'].includes(event.key)" in source
        assert "[data-uxr-edit-target]" in source


# §7.2 condition 1: every refreshed save surface must route BOTH its success and its
# failure text into the live region that surface actually announces through. The
# attribute assertions above only prove the region is correctly roled -- they say
# nothing about what writes to it, so re-pointing a writer at a different (or
# nonexistent) id left the whole gate green. Each entry is
# (source file, live-region id, {outcome: message fragment that must reach it}).
_SAVE_WRITER_TARGETS = (
    (
        "app/static/js/step3_entities.js",
        "save-status",
        {
            "success": "upstream interface(s). ",
            "failure": "Error saving selection.",
        },
    ),
    (
        "app/static/js/step3_entities.js",
        "phase2-status",
        {
            "success": "Samples, mappings, and suggestion review saved.",
            "failure": "Error saving mappings for ",
        },
    ),
    (
        "app/templates/step7_review.html",
        "review-posture-status",
        {
            "success": "Review posture saved.",
            "failure": "Review posture could not be updated.",
        },
    ),
    (
        "app/templates/step2_upstream.html",
        "edge-contract-status",
        {
            "success": "Saved contract reference.",
            "failure": "Select a contract type before saving.",
        },
    ),
    (
        "app/templates/step4_handoffs.html",
        "save-status",
        {
            "success": "Data handoff saved.",
            "failure": "The data handoff could not be saved.",
            # Blocker/warning lists are save outcomes too, and they reach the region
            # through showWarningStatusList rather than showStatus.
            "blocker list": "This data handoff needs attention before it can be saved",
            "saved with warnings": "Saved with guidance.",
        },
    ),
    (
        "app/templates/step5_downstream.html",
        "save-status",
        {
            "success": "Downstream interface saved.",
            "failure": "The downstream interface could not be saved.",
            "blocker list": "This contract needs attention before it can be saved",
            "saved with warnings": "Saved with guidance",
        },
    ),
    (
        # Step 3's identity-role save is a separate announcing region from the
        # phase save-status regions above, with its own writers.
        "app/static/js/step3_entities.js",
        "identity-role-status",
        # The failure text is computed into a variable before the call, so only the
        # success literal is pinnable here -- the severity assertion below is what
        # proves a failure outcome still reaches this region.
        {"success": "identity role decision(s)"},
    ),
    (
        "app/templates/step6_rules.html",
        "save-status",
        {
            "success": "Rule-set saved.",
            "failure": "Rule-set was not saved.",
        },
    ),
)


def _status_writer_payloads(source: str, region_id: str) -> str:
    """Concatenate the arguments of every call that writes into ``region_id``.

    Matches **any** helper that takes the region id as its first argument --
    ``showStatus('x', ...)``, ``showWarningStatusList('x', ...)``, and anything
    added later -- rather than one hard-coded function name. Keying this to
    ``showStatus`` alone made the gate structurally blind to the blocker-list
    writers, so those could be re-pointed with the suite still green.

    The id often sits on its own continuation line, so the match allows whitespace
    (including newlines) between ``(`` and the quoted id, and each call is read
    forward to its terminating ``);`` rather than to end-of-line.
    """
    pattern = re.compile(
        r"\b\w+\(\s*['\"]" + re.escape(region_id) + r"['\"]",
        re.MULTILINE,
    )
    payloads: list[str] = []
    for match in pattern.finditer(source):
        end = source.find(");", match.start())
        payloads.append(
            source[match.start() : end if end != -1 else match.start() + 600]
        )
    return "\n".join(payloads)


def _status_writer_functions(source: str, region_id: str) -> set[str]:
    """Names of the helpers that write into ``region_id``."""
    pattern = re.compile(
        r"\b(\w+)\(\s*['\"]" + re.escape(region_id) + r"['\"]",
        re.MULTILINE,
    )
    return set(pattern.findall(source))


def _status_writer_call_count(source: str, region_id: str) -> int:
    """Count of DISTINCT call sites writing into ``region_id``."""
    pattern = re.compile(
        r"\b\w+\(\s*['\"]" + re.escape(region_id) + r"['\"]",
        re.MULTILINE,
    )
    return len(pattern.findall(source))


# §7.2 requires "any save writer" to be bound -- not just one representative
# success/failure pair per region. A region routinely serves MULTIPLE distinct
# operations (e.g. step6_rules.html's `save-status` serves Rule-set save, Legacy
# Notes save, and KA-rule removal independently); pinning one message per outcome
# proved insufficient because an untouched sibling writer's literal kept the
# aggregate check green even after a DIFFERENT writer was silently re-pointed
# away (round 3 finding: Step 6 Legacy Notes and the Step 2 focused-save failure
# path both escaped this way).
#
# The exact call-site COUNT below is the backstop that closes the class rather
# than one instance of it: redirecting ANY writer -- known or not yet enumerated
# by name -- changes the count for its (file, region) pair and fails here,
# without needing every message literal hand-pinned (there are 81 call sites
# across the six regions; literal-pinning all of them would be both unmaintainable
# and still incomplete the moment a writer is added).
#
# Counts are grounded: generated by running this file's own extraction regex
# against HEAD and recorded verbatim, not estimated. Regenerate deliberately
# (re-run the same regex, update the number) whenever a save writer is added,
# removed, or merged -- an unexplained count change here is exactly the signal
# this test exists to raise.
_EXPECTED_WRITER_COUNTS = {
    ("app/templates/step2_upstream.html", "edge-contract-status"): 15,
    ("app/static/js/step3_entities.js", "save-status"): 3,
    ("app/static/js/step3_entities.js", "phase2-status"): 5,
    ("app/static/js/step3_entities.js", "identity-role-status"): 3,
    ("app/templates/step4_handoffs.html", "save-status"): 11,
    ("app/templates/step5_downstream.html", "save-status"): 17,
    ("app/templates/step6_rules.html", "save-status"): 10,
    ("app/templates/step7_review.html", "review-posture-status"): 3,
}


@pytest.mark.parametrize(
    ("source_path", "region_id", "expected_count"),
    [(path, region, count) for (path, region), count in _EXPECTED_WRITER_COUNTS.items()],
    ids=[f"{Path(p).stem}:{r}" for p, r in _EXPECTED_WRITER_COUNTS],
)
def test_every_known_save_writer_call_site_still_targets_its_region(
    source_path: str, region_id: str, expected_count: int
) -> None:
    source = (ROOT / source_path).read_text()
    actual = _status_writer_call_count(source, region_id)
    assert actual == expected_count, (
        f"{source_path}: {actual} call sites write into '{region_id}', expected "
        f"{expected_count}. If a writer was re-pointed AWAY from this region, a "
        "save outcome that used to announce is now silent -- fix the writer, not "
        "this number. If a writer was genuinely added/removed/merged here on "
        "purpose, regenerate this count from the current source and update the "
        "registry above to match."
    )


@pytest.mark.parametrize(
    ("source_path", "region_id", "outcomes"),
    [(path, region, outcomes) for path, region, outcomes in _SAVE_WRITER_TARGETS],
    # Several surfaces share the id "save-status", so scope each case by source file.
    ids=[
        f"{Path(path).stem}:{region}" for path, region, _ in _SAVE_WRITER_TARGETS
    ],
)
def test_save_outcomes_are_written_into_the_announcing_region(
    source_path: str, region_id: str, outcomes: dict[str, str]
) -> None:
    source = (ROOT / source_path).read_text()
    written = _status_writer_payloads(source, region_id)

    assert written, (
        f"{source_path}: nothing calls showStatus('{region_id}', ...) -- the live "
        "region is announced but never written to, so saves stay silent"
    )
    for outcome, fragment in outcomes.items():
        assert fragment in written, (
            f"{source_path}: the {outcome} message {fragment!r} does not reach "
            f"'{region_id}'. A save outcome that bypasses the announcing region is "
            "silent to assistive technology even though the region is correctly roled."
        )

    # Message literals cannot pin a writer whose text is computed into a variable,
    # so also require that BOTH outcome kinds reach the region by severity.
    assert "'success'" in written, (
        f"{source_path}: no success outcome reaches '{region_id}'"
    )
    assert "'error'" in written or "'warn'" in written, (
        f"{source_path}: no failure outcome reaches '{region_id}' -- a save that "
        "fails would be silent to assistive technology"
    )


def test_blocker_list_writers_are_covered_by_the_writer_gate() -> None:
    """``showWarningStatusList`` is a save-outcome writer too.

    The gate originally matched only ``showStatus``, so every blocker/warning list
    could be re-pointed away from its live region while the suite stayed green.
    This pins the helper itself as in-scope wherever it is used.
    """
    surfaces_using_blocker_lists = {
        "app/templates/step2_upstream.html": "edge-contract-status",
        "app/templates/step4_handoffs.html": "save-status",
        "app/templates/step5_downstream.html": "save-status",
    }
    for source_path, region_id in surfaces_using_blocker_lists.items():
        source = (ROOT / source_path).read_text()
        writers = _status_writer_functions(source, region_id)
        assert "showWarningStatusList" in writers, (
            f"{source_path}: no blocker/warning list reaches '{region_id}' "
            f"(writers found: {sorted(writers)}). Blocker lists are save outcomes "
            "and must be announced, not just rendered."
        )


def test_step2_add_and_focus_saves_share_the_live_status_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _session_with_interfaces()
    add_markup = _render(monkeypatch, "/upstream")
    focus_markup = _render(monkeypatch, "/upstream?focus=account-xml")
    source = (ROOT / "app/templates/step2_upstream.html").read_text()

    for markup in (add_markup, focus_markup):
        assert (
            '<div id="edge-contract-status" class="alert hidden" '
            'style="margin-bottom:12px" role="status" '
            'aria-live="polite"></div>'
        ) in markup
    assert "showStatus('edge-contract-status'" in source
    assert "showWarningStatusList(\n      'edge-contract-status'" in source

    monkeypatch.setenv("EDGEFORGE_STUDIO_UX_REFRESH", "false")
    default_on = client.get("/upstream?focus=account-xml")
    assert default_on.status_code == 200
    assert (
        '<div id="edge-contract-status" class="alert hidden" '
        'style="margin-bottom:12px" role="status" '
        'aria-live="polite"></div>'
    ) in default_on.text
