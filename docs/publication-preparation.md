# Studio publication preparation

## Private Org Release Preparation — 2026-11-07

This is the actual private v5 release-preparation repository,
[edgeforge-suite/EdgeForgeStudio](https://github.com/edgeforge-suite/EdgeForgeStudio),
imported at `db71604c8ba4fbdc8b1c4d4588094933e4a8181c`. The earlier destination
selection and import-pending descriptions below are dated preparation accounts.
The original `santosh-sh` repository, issues, PRs and runs remain the private
pre-v5 development archive; their authentic links are retained, with no issue
migration or promise of public archive access.

Package/runtime metadata is prepared as **5.0.0**, without a release date, tag or
completed acceptance. Python 3.11 support, Studio snapshot 1.4, Engine manifest
2.0 and dependency/runtime inputs remain unchanged. Distribution remains source
and later verified tags, with self-managed builds; no managed deployment or SLA
is offered. The [project-intent statement](../README.md#project-intent-and-community),
two runtime modes and adopter responsibilities remain binding.

Before publication, Suite identifies the exact selected clean Engine/Studio/KS
checkouts for later coordinated acceptance. After verified tags exist, public
instructions use each repository's actual `v5.0.0` tag. The
[newcomer guide](newcomer-journey.md) separates that browser acceptance journey
from the historical fixed-Engine helper and S8 receipt. No future source SHA is
selected here. Final selected Studio/Engine image proof is later work.

Maintainer publication authorization, tested email reporting and PVR verification
at public cutover remain separate gates. This preparation does not enable or
verify those routes. A11y-01, deferred fonts and disclosed M2 residuals remain
OPEN; no image rebuild, accessibility closure, tag or public launch is approved.

## Public-Tree Cleanup - 2026-11-02

[Public-content preparation](public-content-preparation.md) records the bounded
external-material retirement, independent parser/package fixtures and joserfc
1.7.6 correction. The intended fresh tree excludes the retired external input
and identifying historical detail; originals remain in private development
history at the recorded base. The maintained synthetic newcomer journey is
unchanged. This is not an import, visibility change, rights clearance for other
sources, image reassessment, M2 closure or final selected-pair acceptance.
All ownership, security-route activation/testing and publication gates below
remain binding; inherited font, A11y-01 and image limitations remain open.

## Current Private Source Preparation - 2026-10-25

**EF-V5-SOURCE-PREP-STUDIO-S1 revision 1** applies the maintainer-approved
**EF-V5-RELEASE-SCOPE-RESET revision 3**. That decision supersedes conflicting
older gate sequencing; it does not publish a repository, accept vulnerability
risk, or claim the broader M2 programme complete. Entry Studio main is
`74e065a95f0b129fcfd55fbea74412d6634cf17e`; the provisional, frozen Engine proof
reference is `d148ca50722a676359ec7c7296561f79f99e2b69`.

Selected source terms are [Apache-2.0](../LICENSE), copyright Santosh Hommaradi,
with a short [NOTICE](../NOTICE). Inbound contributions use DCO 1.1 sign-offs,
not a CLA. This selection does not resolve third-party notices or generated-app
rights by implication. Maintainer publication authorization remains pending.

The [project-intent statement](../README.md#project-intent-and-community) applies
to this preparation. The maintainer's choice not to monetize adds no restriction
to Apache-2.0 or commercial use by adopters and does not satisfy the pending
publication-authority gate.

**Wording clarification (2026-11-05):** the public gate is described as
maintainer publication authorization. Applicable rights and permissions must
still be verified before exposure; supporting non-public records stay private.
This editorial change grants no clearance and does not change dated proof.

The selected destination is
[edgeforge-suite/EdgeForgeStudio](https://github.com/edgeforge-suite/EdgeForgeStudio).
The current `santosh-sh` repository and old PRs/issues form private pre-v5
reference history. Dated links/identities remain intact; this task does not publish
that history, create a separate archive, migrate issues, or promise public access
to old raw evidence. Current source links target the selected destination, whose
ownership/public availability is not established here.

GitHub Private Vulnerability Reporting and `security@edgeforgesuite.com` are the
selected private routes. [SECURITY.md](../SECURITY.md) explicitly distinguishes
selection from enablement, delivery testing and reachability. No mailbox, DNS,
GitHub setting, response SLA or publication approval is created by this record.
Email activation and delivery testing, plus PVR enablement and private-reporting
verification, are mandatory before public launch; they are not optional post-v5
work and are not represented as completed here.

Under the source-release gate, assessed image residuals and coverage exclusions
remain **OPEN known limitations**, with Studio ownership and material-change /
release-selection review triggers, rather than an implicit risk acceptance or a
claim that every historical M2 question blocks private preparation. Failed
required audits/checks remain blocking. A new critical finding plausibly affecting
shipped behavior must be surfaced, not silently classified away. Final release
selection and applicable new-repository-pair proof are separate later work.

The dated [#318 decision record](handover-evidence/studio-image-residual-decisions-2026-10-20.md)
and [#319 correction](handover-evidence/studio-certifi-pillow-fix-2026-10-20.md)
remain immutable historical evidence, with their actual source/image pairings.
Standalone corrections do not clear private pip/ensurepip, native, OS, JDK,
Maven or whole-stage findings. Fonts remain unavailable by default; A11y-01
remains one FAIL / three NOT RUN with binding automated checks and disclosure.

The [current preparation receipt](handover-evidence/studio-source-preparation-2026-10-25.md)
records the actual provisional image, dependency/audit correction, tested source
and remaining coverage. Optional post-v5 improvements are bounded to one list:
consider real proxy/OIDC integration through its separate design gate, and close
A11y-01 through all four native observations. None is silently implemented or accepted
by this preparation task. Required final release selection, rights/activation
checks and selected-pair proof remain later gates, not optional completion claims.

The earlier publication-preparation account below retains its dated observations.
Its former unresolved terms/contact choices are superseded only by the explicit
selections and still-pending activation/ownership gates above.

## Earlier Preparation Account

Candidate **EF-V5-STUDIO-PUBLICATION-PREP-S1**, revision **1**. Checked
2026-10-10 against Studio `a22b95b7e0d76306064d58953b0d9c4e88f088ef`, including
merged newcomer PR #312. No intervening main changes or open Studio PRs were
observed at entry. This record prepares content; it does not approve publication.

Authority: Engine
[`64f51d0` external-review backlog](https://github.com/santosh-sh/EdgeForge/blob/64f51d0bac92b4c70f26c8f5f067888717df7b14/docs/external-review-backlog.md),
E1/XR-2, RP-EVIDENCE-PURPOSE, XR-5 and parallel ownership. Merged
[KS #44](https://github.com/santosh-sh/EdgeForgeKnowledgeServer/pull/44) supplied
structure only; Studio claims were checked independently. Private repository
links are for authorized readers until separately authorized publication.

## Gaps addressed and source checks

| Observed gap | Prepared result and supporting source |
|---|---|
| SECURITY and handover introduction described only local mode | Corrected to shipped local/shared modes; [settings](../app/services/settings.py), [identity adapters](../app/services/identity.py), [request middleware](../app/middleware/request_context.py) and [SQLite store](../app/services/sqlite_session_store.py) establish anonymous isolation and deferred proxy/OIDC. |
| Deployment wording implied injecting identity was enough | Gateway access and Studio principal attribution are distinct; proxy/OIDC resolve methods raise `IdentityProviderUnavailable`. Real team identity requires separate project work. |
| README called historical v4.1.0 current | Current [package](../pyproject.toml) is 4.2.0; [changelog](../CHANGELOG.md) remains unreleased. Historical tags and evidence remain intact. |
| Scope limits were scattered | Named README scope section explains one manifest/one standalone app, supported paths, adopter authorization and designated preservation seams. [Manifest constant](../app/services/manifest_contract.py) is 2.0; [project model](../app/models/project.py) independently uses 1.4. |
| No bug/feature chooser templates; private contact unresolved | Added synthetic/redacted templates and SECURITY policy chooser link; blank issues stay enabled. No labels, assignees, contact or enabled private-reporting route invented. |
| Governance/legal ownership framed only as an adopter import | Project maintainer owns public-source and inbound terms; adopter owns its use/deployment assessment. Existing LICENSE and CODEOWNERS placeholders are preserved and explicitly unresolved. |
| Evidence index lacked replay availability boundaries | Added audience/purpose, date/source/tool interpretation, reproduction limits and refresh triggers. No historical result or raw archive was rewritten. |

Knowledge Assist stays optional and OFF by default: the
[capability definition](../app/models/project_capabilities.py) and
[assist-service guard](../app/services/assist_service.py) retain that boundary;
[KA-OFF regression checks](../tests/test_studio_ka_off.py) reject hidden KS calls.
Knowledge Server is a separate optional local process. Studio authors/reviews;
Engine owns generation. [Newcomer proof](test-results/newcomer-journey-2026-10-09.md)
and [caller-boundary proof](handover-evidence/studio-adversarial-handoff.md) are
reused, not rerun for prose changes. They do not establish arbitrary
orchestration, universal contract enforcement or production certification.

## Remaining maintainer decisions

This is the consolidated current decision list, reconciled with the approved
source-release scope above. Pending decisions do not make this
documentation slice incomplete; they must be resolved in their applicable later
publication/release work, rather than assumed from a green documentation PR.

| Decision / owner | Concrete unresolved result required |
|---|---|
| Publication authorization — project maintainer | Apache-2.0, Santosh Hommaradi copyright and DCO 1.1/no CLA are selected and applied. Verify applicable rights and permissions before authorizing public exposure; keep supporting non-public records private. Preserve third-party notices and contributors' own certifications. |
| Private security activation — public project maintainer | Before public launch, activate and delivery-test security@edgeforgesuite.com, and enable and verify GitHub PVR's private-reporting path. Both are mandatory; neither is represented as verified by this PR. Keep undisclosed details out of public issues and unverified routes. No SLA is promised. |
| Third-party redistribution/license questions — project maintainer/legal; adopter separately reviews intended use | Resolve dated `caio` UNKNOWN and `certifi` MPL-2.0 flags as applicable, plus OS/JDK/Maven/vendor copies and distributed notices for any selected artifacts. Python declared-license summaries do not cover all image contents or decide generated-app rights. |
| Image limitations and coverage — Studio maintainer/security owners | Carry exact findings, ignored matches and gaps forward as OPEN known limitations under the source-release gate. Reopen on advisory, copy/runtime/recipe, deployment or selected-pair changes. No suppression, risk acceptance or M2 clearance. Preserve fonts and the distinct historical #318/#319 pairings. |
| Final release refs and acceptance — Suite/repository maintainers | Metadata is prepared as 5.0.0; select exact new-repository revisions and perform applicable paired proof under the approved reset scope. Tags, visibility change, full L5 and final browser newcomer acceptance remain later work. #311 is not a corrected-image delivery; #312 is not final selected-release acceptance. |
| Deployment and internal support — adopter / deployment operator | These are adopter responsibilities, not an offered maintainer service. Authenticated team deployment requires real identity integration; operators own IdP/gateway/access policy, retention, backups, approved imports, confidential-data handling, internal support and application business/object/tenant/row authorization. The [project-intent statement](../README.md#project-intent-and-community) defines the maintainer's boundaries; no service, SLA or universal compliance claim is adopted. |

## Open limitations to carry forward

- **A11y-01 is Studio-owned and open.** One native desktop successful-save case
  failed; three cases remain NOT RUN. The [observation record](studio-ux-refresh/pr24a-a11y-walkthrough.md#a11y-01-v5-deferral-evidence)
  preserves the missing transcript and the four exact-speech Safari/VoiceOver
  cases. Existing automated checks remain binding and do not establish speech.
  The policy merged through Studio #299 and Engine #313 makes A11y-01 alone
  non-blocking; authorized public releases/demos still require an audience-accessible
  impact/reproduction notice. [Issue #302](https://github.com/santosh-sh/EdgeForgeStudio/issues/302)
  belongs to the private pre-v5 development archive; it is not a public
  contribution path in this repository. This is not accessibility certification.
- **Image:** the lean image lacks Java font-rendering support by default. Text
  measurement/report/PDF/spreadsheet consumers may need an explicitly extended
  and assessed image. Open findings and coverage exclusions remain visible in
  the evidence index. #311 reused the #310 image; that record did not deliver a
  corrected image. The later [Bundle P transition](handover-evidence/studio-image-bundle-p-2026-10-11.md)
  changes the image to Python 3.13.16 with partial corrections; unresolved vendor,
  native/build families and final selected-pair assessment remain open. It does
  not establish M2 clearance or authorize publication.
- **Newcomer flow:** one macOS/Java17/H2 reference journey and designated hook
  passed at recorded pins. HTTP route automation is not browser observation;
  post-regeneration builds use the managed copy, and fresh H2 runs do not prove
  persistent-data upgrade continuity. Final selected revisions need applicable re-proof.

## Unpublished starter-task drafts

These are two bounded drafts, not published issues, assignments or active work.
The maintainer chooses whether/when to offer them after terms and reporting
decisions. Recruiting contributors is not a release prerequisite. Do not duplicate
an existing owner/issue, apply new labels, or infer authorization to implement.

### Draft 1: Native save-announcement reproduction for A11y-01

- **Reuse/ownership:** existing Studio issue #302; Studio retains review/closeout.
  Open known limitation, not in progress. This draft seeks bounded diagnostic
  evidence, not another competing issue or broad accessibility redesign.
- **Prerequisites:** authorized source access/terms, macOS Safari/VoiceOver with
  Caption Panel, approved OS permission changes, synthetic KA-OFF project and
  [current reproduction](studio-ux-refresh/pr24a-a11y-walkthrough.md).
- **Scope/exclusions:** four desktop/narrow success/failure cases; no Engine/KS,
  new runtime fix, general certification or weakening of automated assertions.
- **Observable completion:** report exact tested SHA, environment/CSS dimensions,
  each verbatim spontaneously announced outcome and PASS/FAIL/INCONCLUSIVE; keep
  missing evidence explicit. Both success cases require `Downstream interface saved.`;
  both failure cases require `This contract needs attention before it can be saved:`
  and `Interface name is required.` All four must pass to close A11y-01; a
  diagnostic contribution can complete while the issue remains open.

### Draft 2: Enforce the existing Studio lint baseline after v5

- **Reuse/ownership:** Studio slice of canonical
  [XR-3](https://github.com/santosh-sh/EdgeForge/blob/64f51d0bac92b4c70f26c8f5f067888717df7b14/docs/external-review-backlog.md#xr-3-blocking-lint-after-v5),
  explicitly **post-v5**. Studio maintainer owns scope and any repository-setting operation.
- **Prerequisites:** v5 timing confirmed, approved bounded implementation, current
  Ruff/rules baseline and existing CI/protection configuration verified.
- **Scope/exclusions:** pin current checker/rules, clean only that baseline and
  enforce the check. No broad style/type migration, dependencies/runtime change,
  sibling CI or unapproved settings operation.
- **Observable completion:** a deliberate representative violation fails the
  enforced check, the corrected revision passes, existing required checks remain
  green and an independent review records the SHA. Any required-check setting
  change receives separate maintainer authorization. This PR performs none of it.

## Bounded content review and validation

The following results are historical 2026-10-10 observations, not a substitute
for this preparation PR's current content, dependency and image checks.

Reviewed changed files and directly relevant active README/security/deployment/
compliance/contributor/evidence guidance for sensitive examples, private host
paths, current claims and public-facing link meaning. Only synthetic examples
and sanitized conclusions belong here; no raw inventories, tokens, logs or
private source archives are added. Repository links can remain inaccessible
outside authorized readers while Studio is private; they are not advertised as
a functioning public report/contribution channel.

This review found stale documentation, not a new demonstrated runtime defect.
The identity stubs, license placeholder and missing verified security route
are explicit existing limitations/decisions above. It is bounded active-content
review, not a fresh full-history secret scan or declaration that every historical
artifact is public-safe. Final publication content/history review remains under
the adopted release scope.

Validation checks relative links/anchors, issue-template front matter, chooser
YAML, changed-file scope and diff hygiene. Setup/install/runtime commands are
unchanged, so no new installation, journey, image scan or Suite campaign is
credited. Required CI and independent review must identify the PR's final SHA;
their documentation checks are not fresh Suite/runtime acceptance.

Local validation on 2026-10-10: the focused settings, manifest, project-file and
KA-OFF checks passed (**128 passed**). Relative-link/anchor, issue-template and
chooser checks passed; README/contributor shell setup blocks are unchanged.
`git diff --check` passed. Exact-head CI and independent-review outcomes are
recorded on the PR, rather than inferred from this local run.
