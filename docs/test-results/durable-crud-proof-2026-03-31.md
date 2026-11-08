# Durable CRUD / File / Staging Proof - 2026-03-31

Historical summary, sanitized for the intended public tree on 2026-11-02.
The external input, copied payloads, identifying output paths and retired runner
remain recoverable only from private development history at Studio
`44ad01f30e4f43f326cfb4304bde704a90606faf`; no new archive is created.

The original recorded run used Studio's merged-through-PR20 baseline (no Studio
SHA was recorded) and Engine `main` at `c37d4d2`, advanced from `e4baebe` to include
merged fixes through Engine PR #54. These are the historical execution baselines;
the later private recovery revision above is not a tested March baseline.

The original run reported successful Studio intake, entity/operation selection,
sample/mapping authoring, fixed-width downstream and staging handoff saves,
manifest export/validation, generation, Maven build, startup, CRUD requests and
batch/handoff output. Completeness was 14 READY, 2 WARNING, 0 MANUAL_FOLLOW_UP;
generation wrote 29 files including 22 Java sources and reported harness PASSED.
The exported manifest was the then-current 1.0 contract, not today's 2.0.

Limitations remain: pagination wrappers introduced nullable transport fields;
the run did not prove strict canonical pruning or schema/code-preserving
regeneration. UUID-style identifiers required wider file and staging columns.
The proof-side width and writer-filename adjustments were not Engine fixes.
Local process/network access was required. This dated result is not current
acceptance or a public reproduction recipe.

The replacement synthetic fixtures did **not** produce this historical result.
Current maintained authoring and preservation instructions are in the
[newcomer journey](../newcomer-journey.md); new checks and their actual source
identities are recorded in [public-content preparation](../public-content-preparation.md).
