<!--
EdgeForge Studio pull request. See CONTRIBUTING.md for the authoritative rules and
README.md for the wizard flow and how to run Studio.
-->

## What

<!-- What does this PR change? -->

## Why

<!-- What problem does this solve? -->

Linked issue: <!-- Link the owning issue and confirmed scope, or explain if none applies. -->

## Validation

<!-- Record commands actually run, results and untested limitations, including
     Engine/JDK/Maven prerequisites and skipped integration tests. Prose-only
     changes need content/link checks, not new tests that merely assert wording. -->

<!-- Use minimal synthetic examples and redact diagnostics. Suspected undisclosed
     vulnerabilities belong in the private process in SECURITY.md, not this PR.
     State the tested SHA, actual results, skips and evidence limitations. -->

## Contract / scope risk

<!-- Does this affect the emitted manifest package, the manifest 2.0 contract, the
     KA-OFF default behavior, or add an auth/multi-user surface? Call out any
     backward-compatibility risk to existing packages explicitly, or state "none". -->

## Checklist

- [ ] PR-only — not pushed or merged directly to `main`
- [ ] Branch follows `<agent>/{feature|fix|docs|chore}/<short-desc>`
- [ ] PR title uses a prefix: `[FEATURE]` / `[FIX]` / `[DOCS]` / `[CHORE]`
- [ ] Stays within the paired Engine manifest 2.0 contract (no manifest-1.0 bridge)
- [ ] Studio authors/reviews — does not generate code or mutate generated apps directly
- [ ] Knowledge Assist OFF-by-default behavior preserved
- [ ] No new auth / shared-mode / multi-user behavior without an approved design gate
- [ ] Applicable checks passed; behavior changes have regression coverage (record skips and Engine/Maven prerequisites)
- [ ] Review identifies the exact head SHA; fixes require applicable CI and review again
- [ ] Apache-2.0 and third-party notices preserved; contribution commits carry the contributor's DCO 1.1 sign-off (`git commit -s`; no CLA)
- [ ] No secrets, private employer/customer material or real/production data; fixtures are synthetic

<!-- Necessary public dependency names, upstream references and attribution are
     permitted under CONTRIBUTING.md; preserve applicable permissions and notices. -->
