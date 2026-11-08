# Failure-State Coverage — per-surface PR acceptance checklist

**Paste this into every refreshed board/editor/inspector PR description (and its build packet). It is an
active merge gate, not a design artifact.** Record **contract facts only** — no prescribed visuals, no
invented thresholds, no universal interaction rules; the *treatment* is the surface's own call. Give
**all ten** states an explicit disposition: `Covered`, `N/A — <reason>`, or `Deferred — <PR/owner>`.

> Consensus origin: Codex build thread + studio review thread (2026-07-11) after the visual "gallery"
> attempt was found to over-prescribe treatment. Keep this facts-only so it can't drift the same way.

### Failure-State Coverage

| State | Disposition | Source of truth · proof (test / manual / N/A reason / deferred PR) |
|---|---|---|
| Empty | Covered / N/A / Deferred | |
| Overflow (50+) | | |
| Long path | | |
| Nested XML | | |
| Unresolved import | | |
| Duplicate name | | |
| Parser failure | | |
| Stale after back | | |
| Paste conflict | | |
| Keyboard only | | |

**Contract mechanics — check where applicable (link the test/proof):**
- [ ] Readiness preserves precedence + policy (**impl §1.2**): `blocks_export > needs_action > warning >
      draft > ready` — `warning` = export allowed · `needs_action` = continue allowed, **export may or may
      not be allowed** (per the §1.2 parity rule, `export_blocking == package_writer would block it`) ·
      `blocks_export` = export disabled · `draft` = intentionally incomplete (blocks only if in the active
      package). States never conflated in counts or summaries.
- [ ] **Unresolved import = deterministic _warning_** (export allowed) — **not** automatically
      `blocks_export` (proposal-final.md, round-2 hardening / security-scoped helper acceptance).
- [ ] No blocker can be hidden by filtering, collapsing, or pagination.
- [ ] Parsing uses **server-side inspectors only** (no browser DOMParser). Nested / oversized / deep XML →
      **XXE/DTD rejected · path traversal refused · depth+size bounds · deterministic error shapes** (§1.4).
- [ ] Seed / patch (§1.4): applies **only checked rows into empty fields**; collisions stay **unchecked +
      labelled**; no-match stays blank; every applied value carries `DERIVED` + basis; provenance is
      **recomputed, never persisted**.
- [ ] Rename = **atomic replace keyed by `original_name`** (§1.3) — a rename into an existing name hits the
      same duplicate-name path.
- [ ] Save-one failure returns the full envelope `{ok:false, blockers:[{code,label,field_ref,section_ref}]}`
      → tab badge + field focus (PR-16).
- [ ] **No optimistic client write** on a failed save (board row / stats / rail unchanged until server ok).
- [ ] Conflict echo (§1.3): request carries `source_of_truth_version`; server returns `409 + fresh item`
      on mismatch. **The multi-session track (#200) is already on `main`** — so each new save-one route
      **carries the version and enforces + tests `409 + fresh item` as it lands** (not deferred to a future
      landing).
- [ ] A11y (§1.5): **text contrast ≥ 4.5:1** on every zone · every family/state/provenance signal carries a
      text label / `aria-label` (never colour alone) · **error ≠ red-only** · **visible focus on every
      state** · **arrow/Enter board path** · save success/failure **announced to SR**.
- [ ] Deep-link / focus behaviour honoured where applicable (e.g. Step-7 "Fix ↗" lands on the exact field).

### Applicability guidance (mark inapplicable rows `N/A — <reason>`)
- **Nested XML · Unresolved import** → ingest / inspector surfaces (XSD/WSDL) only. N/A elsewhere.
- **Paste conflict** → editors with seed-from-paste / schema. N/A on read-only boards.
- **Overflow (50+)** → **any surface that can present a large repeated collection — including single-item
  editors with >50 fields/rows** (e.g. the Step-3 entity detail, impl PR-10 / proposal-final.md). Mark N/A
  **only** when the surface cannot present a large collection.
- **Duplicate name · Stale after back** → principally **create / rename / save-one editor** concerns
  (validation + save-time conflict). N/A on read-only or non-editing surfaces.
- **Empty · Long path · Keyboard only** → apply to most board + editor surfaces; justify any N/A.

### Out of scope for this checklist (separate, single-PR checks)
- **Async-DDL *pending* state** — a PR-14 (Step-4 handoff) concern only; not a general failure state.
- **Modal focus-trap / restore** — **N/A: PR-18's modal is retired.** Keyboard-only operation,
  route/back + dirty-guard behaviour, visible focus, and screen-reader save announcements remain
  required on the full-page and split presentations. PR-24a gates all of these, and test-enforces the
  **structural** save-announcement contract (live-region attributes *and* writer→region binding);
  observing announcements **spoken** remains the open **A11y-01** gate. Its four native cases are
  unchanged. The [proposed §7.3 sequencing change](implementation-design.md#a11y-01-v5-baseline-deferral)
  remains non-operative until the Studio and Engine/Suite amendments are independently reviewed and
  merged; once active, A11y-01 alone will not block source publication, internal baselines/tags,
  public releases, or promoted demos. A11y-01 remains an
  [open known limitation](https://github.com/santosh-sh/EdgeForgeStudio/issues/302), and structural
  save-announcement checks remain active and mandatory.

*Do not encode specific treatments here (ellipsis vs truncation, collapse thresholds, exact error codes,
key bindings beyond the §1.5 arrow/Enter/announce contract). Those are per-surface design decisions,
reviewed in the PR — this gate only asks that each applicable state has a disposition and its contract
facts hold.*
