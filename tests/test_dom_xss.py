"""Stored DOM-XSS regression coverage for Studio's dynamic HTML builders."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.models.project import KafkaTopicPair
from tests.session_helpers import reset_session, save_session

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "app" / "templates"
STATIC_JS = ROOT / "app" / "static" / "js"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "security"
STUDIO_JS = STATIC_JS / "studio.js"
NODE = shutil.which("node")
CLIENT = TestClient(app)

# Each digest covers the complete contents of a sink-bearing file. The
# syntax-aware count catches newly introduced access forms, while the file
# boundary prevents multiline sink edits or same-count substitutions from
# bypassing an explicit security review.
DYNAMIC_HTML_SINK_MANIFEST: dict[str, dict[str, str | int]] = {
    "app/static/js/step3_entities.js": {
        "count": 22,
        "sha256": "aeead74c0463675b9a98e7de4a09fb08b605562ffc5578f905cff78ff225cfcc",
    },
    "app/static/js/studio.js": {
        "count": 12,
        "sha256": "32d0c1d0dc53e61f9ba14b8701675d909c3dfde2974b12366b24beeb75cb3ffd",
    },
    "app/templates/kafka_step1_topics.html": {
        "count": 1,
        "sha256": "2eda3618a07484012cc6596b1d9c89cd3d30b2e6a39f39bd4c9a677ab83d49b6",
    },
    "app/templates/kafka_step2_routes.html": {
        "count": 7,
        "sha256": "83a0370c306d5b254ea269aadef21545c0baa166a4dbcbdeb9c2cd548f01dbdf",
    },
    "app/templates/kafka_step3_transforms.html": {
        "count": 3,
        "sha256": "7501904a74bb7b83f822f433e22aba0f6277d1a98f5666be13ae34dec0c8ec7d",
    },
    "app/templates/step2_upstream.html": {
        "count": 12,
        "sha256": "e124dea15cc8a188767dc9a1eb9e4a13da9fcc711e6040096b51ca54d98a4a91",
    },
    "app/templates/step3_passthrough.html": {
        "count": 10,
        "sha256": "e4a83dac979b79fc6989ce5c7af1b8b2cfc7c5c5da99bf534ba088647c586e66",
    },
    "app/templates/step4_handoffs.html": {
        "count": 4,
        "sha256": "f902ff46b1bb968d0d763642df8c0fec980283104f6f9d4e8df720ac33799ac2",
    },
    "app/templates/step5_downstream.html": {
        "count": 18,
        "sha256": "d610f5466101af178eeb6ddc74c05de4a98f9fe5fa0942db012f42af4f8ffce2",
    },
    "app/templates/step6_rules.html": {
        "count": 16,
        "sha256": "6da7b501638762333106f19713a027439c077268630b53cf8884603c6859cd94",
    },
    "app/templates/step8_export.html": {
        "count": 10,
        "sha256": "177a1fe6e59457e23d785e4c9af08bc6e0583d82583a6974cc40a8715ada4c6a",
    },
}
SINK_PATTERN = re.compile(
    r"""
    (?:
      (?:\.\s*(?:innerHTML|outerHTML)|
         \[\s*['"](?:innerHTML|outerHTML)['"]\s*\])
      \s*(?:\?\?=|&&=|\|\|=|>>>=|<<=|>>=|\*\*=|[+\-*/%&|^]=|=)
      |
      (?:\.\s*insertAdjacentHTML|
         \[\s*['"]insertAdjacentHTML['"]\s*\])
      \s*\(
    )
    """,
    re.VERBOSE,
)
UNQUOTED_DYNAMIC_ATTRIBUTE = re.compile(
    r"\s[A-Za-z_:][-A-Za-z0-9_:.]*\s*=\s*(?:\$\{|\{\{)"
)


class _MarkupProbe(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self._textarea_classes: list[str] = []
        self.textarea_text: dict[str, str] = {}

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        normalized = dict(attrs)
        self.elements.append((tag, normalized))
        if tag == "textarea":
            class_name = normalized.get("class") or ""
            self._textarea_classes.append(class_name)
            self.textarea_text.setdefault(class_name, "")

    def handle_endtag(self, tag: str) -> None:
        if tag == "textarea" and self._textarea_classes:
            self._textarea_classes.pop()

    def handle_data(self, data: str) -> None:
        if self._textarea_classes:
            self.textarea_text[self._textarea_classes[-1]] += data

    def attribute(self, class_name: str, name: str) -> str | None:
        for _, attrs in self.elements:
            if class_name in (attrs.get("class") or "").split():
                return attrs.get(name)
        raise AssertionError(f"No element with class {class_name!r}")


def setup_function() -> None:
    reset_session()


def teardown_function() -> None:
    reset_session()


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_block(source: str, name: str, next_name: str) -> str:
    start = source.index(f"function {name}(")
    end = source.index(f"\nfunction {next_name}(", start)
    return source[start:end]


def _async_function_block(source: str, name: str, next_name: str) -> str:
    start = source.index(f"async function {name}(")
    end = source.index(f"\nfunction {next_name}(", start)
    return source[start:end]


def _shared_encoder_source() -> str:
    source = _source(STUDIO_JS)
    start = source.index("function escapeHtml(")
    end = source.index("// Public, DOM-free seed-patch unit.", start)
    return source[start:end]


def _run_node(parts: list[str], expression: str, payload: object) -> dict:
    assert NODE, "Stored-XSS markup tests require Node; no npm packages are used."
    harness = "\n".join(
        [
            "const window = globalThis;",
            _shared_encoder_source(),
            "const payload = JSON.parse(require('fs').readFileSync(0, 'utf8'));",
            *parts,
            "(async () => {",
            f"  const result = await ({expression});",
            "  process.stdout.write(JSON.stringify({",
            "    result,",
            "    executed: globalThis.__storedXss || 0,",
            "  }));",
            "})().catch(error => {",
            "  console.error(error.stack || error);",
            "  process.exit(1);",
            "});",
        ]
    )
    completed = subprocess.run(
        [NODE, "-e", harness],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _probe(markup: str) -> _MarkupProbe:
    probe = _MarkupProbe()
    probe.feed(markup)
    return probe


def _assert_no_injected_executable_markup(probe: _MarkupProbe) -> None:
    assert not {"script", "img", "svg"} & {tag for tag, _ in probe.elements}
    for _, attrs in probe.elements:
        assert "onerror" not in attrs
        assert "onload" not in attrs
        assert "onfocus" not in attrs
        assert "autofocus" not in attrs


def _hostile_saved_project() -> dict:
    return json.loads((FIXTURES / "hostile_saved_project.json").read_text(encoding="utf-8"))


def _sink_identities(relative_path: str, source: str) -> list[str]:
    identities = []
    for match in SINK_PATTERN.finditer(source):
        line_number = source.count("\n", 0, match.start()) + 1
        line_start = source.rfind("\n", 0, match.start()) + 1
        line_end = source.find("\n", match.end())
        if line_end < 0:
            line_end = len(source)
        normalized_line = " ".join(source[line_start:line_end].split())
        access = re.sub(r"\s+", "", match.group(0))
        identities.append(
            f"{relative_path}:{line_number}:{access}:{normalized_line}"
        )
    return identities


def _sink_manifest_entry(relative_path: str, source: str) -> dict[str, str | int]:
    identities = _sink_identities(relative_path, source)
    digest = hashlib.sha256(source.encode()).hexdigest()
    return {"count": len(identities), "sha256": digest}


def test_dynamic_html_sink_inventory_is_complete() -> None:
    actual: dict[str, dict[str, str | int]] = {}
    for root in (TEMPLATES, STATIC_JS):
        for path in root.rglob("*"):
            if path.suffix not in {".html", ".js"}:
                continue
            relative_path = str(path.relative_to(ROOT))
            entry = _sink_manifest_entry(relative_path, _source(path))
            if entry["count"]:
                actual[relative_path] = entry

    assert actual == DYNAMIC_HTML_SINK_MANIFEST


def test_sink_discovery_covers_compound_and_bracket_assignment_forms() -> None:
    source = """
node.innerHTML = safe;
node.innerHTML += attacker;
node['innerHTML'] ||= attacker;
node["outerHTML"] = attacker;
node.insertAdjacentHTML('beforeend', attacker);
node['insertAdjacentHTML']('beforeend', attacker);
"""

    identities = _sink_identities("mutation.js", source)

    assert len(identities) == 6
    assert any(".innerHTML+=" in identity for identity in identities)
    assert any("['innerHTML']||=" in identity for identity in identities)
    assert any('["outerHTML"]=' in identity for identity in identities)
    assert any("['insertAdjacentHTML'](" in identity for identity in identities)


def test_sink_manifest_rejects_same_count_unsafe_substitution() -> None:
    baseline = """
first.innerHTML = escapeHtml(value);
second.innerHTML = '<span>Fixed markup</span>';
"""
    mutated = """
first.innerHTML = attackerControlledValue;
second.innerHTML = '<span>Fixed markup</span>';
"""

    baseline_entry = _sink_manifest_entry("mutation.js", baseline)
    mutated_entry = _sink_manifest_entry("mutation.js", mutated)

    assert baseline_entry["count"] == mutated_entry["count"] == 2
    assert baseline_entry["sha256"] != mutated_entry["sha256"]


def test_sink_manifest_rejects_unsafe_multiline_body_mutation() -> None:
    baseline = """
panel.innerHTML = `
  <span>${escapeHtml(attackerControlledValue)}</span>
`;
"""
    mutated = """
panel.innerHTML = `
  <span>${attackerControlledValue}</span>
`;
"""

    baseline_entry = _sink_manifest_entry("mutation.js", baseline)
    mutated_entry = _sink_manifest_entry("mutation.js", mutated)

    assert baseline_entry["count"] == mutated_entry["count"] == 1
    assert baseline_entry["sha256"] != mutated_entry["sha256"]


def test_one_audited_encoder_owns_text_and_quoted_attribute_encoding() -> None:
    hostile = "'\"><img src=x onerror=\"globalThis.__storedXss=1\">&"
    result = _run_node(
        [],
        """({
          encoded: escapeHtml(payload),
          text: `<span>${escapeHtml(payload)}</span>`,
          doubleQuoted: `<input class="double" value="${escapeHtml(payload)}">`,
          singleQuoted: `<input class='single' value='${escapeHtml(payload)}'>`,
        })""",
        hostile,
    )

    assert result["executed"] == 0
    assert result["result"]["encoded"] == (
        "&#39;&quot;&gt;&lt;img src=x "
        "onerror=&quot;globalThis.__storedXss=1&quot;&gt;&amp;"
    )
    for key in ("text", "doubleQuoted", "singleQuoted"):
        probe = _probe(result["result"][key])
        _assert_no_injected_executable_markup(probe)
    assert _probe(result["result"]["doubleQuoted"]).attribute("double", "value") == hostile
    assert _probe(result["result"]["singleQuoted"]).attribute("single", "value") == hostile

    implementations = []
    for root in (TEMPLATES, STATIC_JS):
        for path in root.rglob("*"):
            if path.suffix in {".html", ".js"} and "function escapeHtml(" in _source(path):
                implementations.append(str(path.relative_to(ROOT)))
    assert implementations == ["app/static/js/studio.js"]


def test_dynamic_unquoted_attribute_values_are_prohibited() -> None:
    offenders: list[tuple[str, str]] = []
    for root in (TEMPLATES, STATIC_JS):
        for path in root.rglob("*"):
            if path.suffix not in {".html", ".js"}:
                continue
            for tag in re.findall(r"<[^>]+>", _source(path), re.DOTALL):
                if UNQUOTED_DYNAMIC_ATTRIBUTE.search(tag):
                    offenders.append((str(path.relative_to(ROOT)), tag))

    assert offenders == []


def test_hostile_saved_kafka_project_cannot_break_out_of_card_markup() -> None:
    fixture = _hostile_saved_project()
    pair = fixture["kafka_topic_pair"]
    source = _source(TEMPLATES / "kafka_step1_topics.html")
    result = _run_node(
        [_function_block(source, "topicCardTemplate", "addRouteCard")],
        "topicCardTemplate(payload)",
        pair,
    )

    assert result["executed"] == 0
    probe = _probe(result["result"])
    _assert_no_injected_executable_markup(probe)
    assert probe.attribute("route-name", "value") == pair["route_name"]
    assert probe.attribute("upstream-topic", "value") == pair["upstream_topic"]
    assert probe.attribute("downstream-topic", "value") == pair["downstream_topic"]
    assert probe.textarea_text["upstream-schema-content"] == pair["upstream_schema_content"]
    assert probe.textarea_text["downstream-schema-content"] == pair["downstream_schema_content"]


def test_hostile_saved_project_is_json_encoded_before_browser_restore() -> None:
    pair = _hostile_saved_project()["kafka_topic_pair"]
    session = reset_session()
    session.app_archetype = "kafka-integration"
    session.kafka_topic_pairs = [KafkaTopicPair.model_validate(pair)]
    save_session(session)

    response = CLIENT.get("/kafka/topics")

    assert response.status_code == 200
    assert "<img src=x onerror=" not in response.text
    assert "</textarea><script>globalThis.__storedXss=6</script>" not in response.text
    assert "\\u003cimg" in response.text
    assert "\\u003c/textarea\\u003e\\u003cscript\\u003e" in response.text


def test_hostile_openapi_descriptor_cannot_break_passthrough_markup() -> None:
    spec_content = (FIXTURES / "hostile_openapi.json").read_text(encoding="utf-8")
    described = CLIENT.post(
        "/passthrough/describe-spec",
        json={"source_mode": "text", "spec_content": spec_content},
    )
    assert described.status_code == 200, described.text
    operation = described.json()["operations"][0]
    assert "<svg" in operation["name"]
    assert any("<script>" in field for field in operation["request_fields"])

    fixture = _hostile_saved_project()
    target = {
        **fixture["passthrough_target"],
        "operations": [operation],
        "selected_operation_name": operation["name"],
        "selected_operation": operation,
    }
    source = _source(TEMPLATES / "step3_passthrough.html")
    result = _run_node(
        [
            _function_block(source, "makeSelectOptions", "currentSystems"),
            _function_block(source, "targetCardTemplate", "addTargetCard"),
        ],
        "targetCardTemplate(payload)",
        target,
    )

    assert result["executed"] == 0
    probe = _probe(result["result"])
    _assert_no_injected_executable_markup(probe)
    assert probe.attribute("target-name-input", "value") == target["name"]
    assert probe.attribute("target-system-input", "value") == target["system"]
    assert probe.attribute("target-spec-url", "value") == target["spec_url"]
    assert probe.textarea_text["target-spec-content"] == target["spec_content"]


def test_hostile_operation_name_completes_step3_sample_and_mapping_collection() -> None:
    spec_content = (FIXTURES / "hostile_openapi.json").read_text(encoding="utf-8")
    described = CLIENT.post(
        "/passthrough/describe-spec",
        json={"source_mode": "text", "spec_content": spec_content},
    )
    assert described.status_code == 200, described.text
    operation = described.json()["operations"][0]
    source = _source(STATIC_JS / "step3_entities.js")
    harness = """
const calls = [];
const mappingRow = {
  querySelector(selector) {
    if (selector === '.mapping-source') return { value: 'currency_code' };
    if (selector === '.mapping-target') return { value: 'Account.currencyCode' };
    return null;
  },
};
const requestContainer = {
  dataset: { iface: payload.interfaceName, op: payload.operation.name },
  querySelectorAll(selector) {
    if (selector !== 'tr') throw new Error(`Unexpected request selector: ${selector}`);
    return [mappingRow];
  },
};
const responseContainer = {
  dataset: { iface: payload.interfaceName, op: payload.operation.name },
  querySelectorAll(selector) {
    if (selector !== 'tr') throw new Error(`Unexpected response selector: ${selector}`);
    return [];
  },
};
const sampleTextarea = {
  dataset: { op: payload.operation.name, kind: 'request' },
  value: '{"currency_code":"USD"}',
};
const panel = {
  dataset: { ifaceName: payload.interfaceName },
  querySelectorAll(selector) {
    if (selector === 'textarea[data-iface]') return [sampleTextarea];
    if (selector === '.op-req-mapping-rows[data-iface], .op-resp-mapping-rows[data-iface]') {
      return [requestContainer, responseContainer];
    }
    if (selector === '.op-req-mapping-rows') return [requestContainer];
    if (selector === '.op-resp-mapping-rows') return [responseContainer];
    throw new Error(`Unsafe or unexpected selector: ${selector}`);
  },
};
const document = {
  querySelectorAll(selector) {
    if (selector !== '#interface-panels [data-iface-name]') {
      throw new Error(`Unexpected document selector: ${selector}`);
    }
    return [panel];
  },
};
async function postJSON(url, body) {
  calls.push({ url, body });
  return { ok: true };
}
async function saveSuggestionReview() {
  return { ok: true };
}
function showStatus() {}
function setTimeout() {}
"""
    result = _run_node(
        [
            harness,
            _async_function_block(
                source,
                "saveSamplesAndContinue",
                "skipSamples",
            ),
        ],
        "saveSamplesAndContinue().then(() => calls)",
        {
            "interfaceName": "iface\"><img src=x onerror=\"globalThis.__storedXss=20\">",
            "operation": operation,
        },
    )

    assert result["executed"] == 0
    assert [call["url"] for call in result["result"]] == [
        "/mappings/upstream/samples/save",
        "/mappings/upstream/save",
    ]
    mapping_body = result["result"][1]["body"]
    assert mapping_body["interface_name"].startswith('iface"><img')
    assert mapping_body["operation_mappings"] == [
        {
            "name": operation["name"],
            "request_mappings": [
                {
                    "source": "currency_code",
                    "target": "Account.currencyCode",
                }
            ],
            "response_mappings": [],
        }
    ]


def test_confirmed_attacker_influenced_sinks_use_shared_encoding() -> None:
    passthrough = _source(TEMPLATES / "step3_passthrough.html")
    rules = _source(TEMPLATES / "step6_rules.html")
    step3 = _source(STATIC_JS / "step3_entities.js")
    handoffs = _source(TEMPLATES / "step4_handoffs.html")
    downstream = _source(TEMPLATES / "step5_downstream.html")

    assert 'value="${escapeHtml(target?.name || \'\')}"' in passthrough
    assert "${escapeHtml(target?.spec_content || '')}</textarea>" in passthrough
    assert 'value="${escapeHtml(route?.match || \'\')}"' in passthrough
    assert '<option value="${escapeHtml(field.name)}">' in rules
    assert "<option value=\"${escapeHtml(name)}\">" in rules
    assert "target = ${escapeHtml(iface.entity_name)}.field" in step3
    assert "candidate.dataset.suggestionId === suggestionId" in step3
    assert 'value="${escapeHtml(prefill?.name || \'\')}"' in handoffs
    assert 'placeholder="${escapeHtml(srcHint)}"' in downstream
