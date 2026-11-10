# One local journey: author, run, change and regenerate

This journey uses the maintained [synthetic Account sample](sample-packs/fs-account-servicing/README.md).
It keeps Knowledge Assist **OFF**; Knowledge Server is not needed. Studio authors
manifest **2.0** and invokes Engine; saved Studio project **1.4** is a separate
contract. Use synthetic or approved content only: Studio does not sanitize
uploads, and project state and exports may retain them.

## Reference and prerequisites

For v5, use the Engine, Studio and Knowledge Server source revisions identified
by Suite's coordinated release selection. Before publication, the release
operator uses those exact selected clean checkouts with `edgeforge-suite`
origins. After verified tags exist, clone each actual repository
([Engine](https://github.com/edgeforge-suite/EdgeForge),
[Studio](https://github.com/edgeforge-suite/EdgeForgeStudio),
[Knowledge Server](https://github.com/edgeforge-suite/EdgeForgeKnowledgeServer))
and check out its actual `v5.0.0` tag. Final source SHAs are a later Suite
selection; this guide does not choose them.

Use Python 3.11, JDK 17 and Maven 3.9+. The
[earlier S8 receipt](test-results/newcomer-journey-2026-10-09.md) and
`scripts/newcomer_journey.py` describe their historical pair, including fixed
Engine `64f51d0bac92b4c70f26c8f5f067888717df7b14`; they do not validate arbitrary
new refs or final v5 sources. Final acceptance repeats the browser
author/generate/run/change/regenerate journey below and records its actual
selected sources, environment and outcomes. No runtime proof is repeated by this
documentation update.

The historical reference is local macOS/ARM64 with H2 in memory, not a deployment
or an all-platform promise. Select `springboot-legacy-compatible` explicitly in
Step 1 instead of this pack's enterprise/PostgreSQL default. This is a supported
profile choice in your working project, not a change to the maintained sample.

You need authorized source access and dependency-download access to PyPI and
Maven repositories. No Docker, PostgreSQL server, KS or image scan is needed.
Install each repository in its **own** virtual environment; do not borrow
another task's environment. In Studio:

```sh
python3.11 -m venv --copies .venv
.venv/bin/python -m pip install -c constraints.txt pip setuptools wheel
.venv/bin/python scripts/verify-packaging-toolchain.py
.venv/bin/python -m pip install -r requirements.txt -c constraints.txt
.venv/bin/python -m pip check
```

In the selected Engine checkout, follow its constrained setup:

```sh
python3.11 -m venv --copies .venv
.venv/bin/python -m pip install -c requirements-lock.txt -r requirements.txt
.venv/bin/python -m pip check
```

Create environments only when `.venv` is absent. Keep Engine, Studio and optional
KS dependencies in separate environments with no global-package fallback. KS is
not launched for this KA-OFF journey; any coordinated KS setup follows that
selected checkout's own constraints. Copied environments support the later Suite
launch checks; creation alone does not prove interpreter provenance or acceptance.

Check `java -version` and `mvn --version`: **both must use Java 17**. Set
`JAVA_HOME` and `PATH` to the same installed JDK if they disagree. The receipt
records actual versions and exact source SHAs, rather than assuming them.

## Start and open

From Studio, start an isolated loopback-only server:

```sh
export EDGEFORGE_STUDIO_STATE_DIR="$(mktemp -d)/studio-state"
export EDGEFORGE_STUDIO_SHARED_MODE=false
export EDGEFORGE_STUDIO_REGEN_PREVIEW_ENABLED=true
echo "$EDGEFORGE_STUDIO_STATE_DIR"
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8080
```

The regeneration flag is preview/opt-in; this exercise does not change defaults.
Open `http://127.0.0.1:8080` in one browser session. **Open Project** with
`docs/sample-packs/fs-account-servicing/project/fs-account-servicing.edgeforge-project.json`.
Review Step 1, choose `springboot-legacy-compatible`, and set the Engine path to
your selected Engine checkout. Keep KA off.

For this preview flow, output must be inside the session workspace. In a second
terminal, set `EDGEFORGE_STUDIO_STATE_DIR` to the path printed above; environment
variables are not inherited by a separate terminal. List the newly created
directory under `$EDGEFORGE_STUDIO_STATE_DIR/workspaces`. With this fresh state and one browser session
there is one. Set Step 1 **Output Path** to that directory plus `/output`.
Do not point at another session or a source repository. Save Step 1.

Review Steps 2-7: `Account`, selected `createAccount`, explicit request/response
mappings, the staging handoff, end-of-day file contract and allowed-status rule.
Keep only `createAccount` selected in Step 3 for this exercise. Do not interpret
the sample's unselected list/filter or computed-read descriptions as tested
behavior. The existing A11y-01 [spoken-save limitation](studio-ux-refresh/pr24a-a11y-walkthrough.md#a11y-01-v5-deferral-evidence)
remains open; this journey supplies no native accessibility observation.

## Generate, build and exercise

In Step 8 choose **Export**, **Validate**, **Generate**, **Build**, then **Run**.
Wait for the running URL. Use its loopback port below, not Studio's port:

```sh
curl -i -H 'Content-Type: application/json' -d '{"accountId":"ACCT-S8-001","customerId":"CUST-INPUT","status":"OPEN","balance":1250.0,"currencyCode":"USD","openedAt":"2026-01-15"}' http://127.0.0.1:APP_PORT/accounts
curl -i http://127.0.0.1:APP_PORT/accounts/ACCT-S8-001
curl -i http://127.0.0.1:APP_PORT/accounts/ACCT-MISSING
```

Expect **201** with the supplied synthetic fields, **200** with the persisted
values, and **404** for the missing ID. A health response alone is not success.
Stop the app using Step 8 **Stop**.

## Add developer-owned behavior

The preview flow captures a **managed copy**. **Save Project** downloads a
JSON file. Open that downloaded file and read its
`last_generated_package_ref`; resolve this relative to the session workspace found above.
Call that directory `MANAGED_APP`. Do not edit baseline hashes or manifests.
Studio's Step 8 Build & Run still targets the original `output/.../generated-app`,
not the managed copy used by preview/apply. The remaining build/run steps below
therefore deliberately use Maven/Java in `MANAGED_APP`; do not mistake a rebuild
of the original output for post-regeneration proof.

In `MANAGED_APP/src/main/java/com/appbuilder/account_servicing/service/AccountService.java`,
which is marked `EdgeForge-ownership: developer`, replace only the body of
`beforeCreate(Account account)` with:

```java
account.setCustomerId("CUST-S8-HOOK");
```

This synthetic witness demonstrates the declared service hook, not a suggested
customer-ID policy. Do **not** edit `AccountServiceBase` or another generated-owned
file. Keep the entire developer file's bytes/hash for comparison after apply.

In `MANAGED_APP`, run `mvn -B -ntp clean verify`. Confirm Surefire reports show
tests executed, with zero failures/errors/skips. Studio's Build button uses
`-DskipTests`, so it does not establish this proof. Start the built application
with `java -jar target/account-servicing-0.0.1-SNAPSHOT.jar --server.address=127.0.0.1 --server.port=18090`.
Repeat create/read: `customerId` must now be `CUST-S8-HOOK`. Stop this Java process
before preview/apply. H2 is in memory, so every process starts with a fresh database.

## Author one additive change

1. Copy the sample's `contracts/account-api-spec.json` outside the repository.
   Add `nickname` to `components.schemas.Account.properties` with
   `{"type":"string","maxLength":40,"default":"UNNAMED"}`. Keep all other contracts.
2. Upload that copy in Step 2. In Step 3 select `Account` and `createAccount` again.
3. Add `"nickname":"SYNTHETIC-NICKNAME"` to the create request and response samples.
   Save both. Add `nickname` to `Account.nickname` in **both** mapping directions
   and save mappings.
4. In Step 6 add a **Default** rule for `nickname`, value `UNNAMED`, preserving
   the existing rules. Save the rule set. The historical reference Engine emitted a **nullable**
   `nickname VARCHAR(255) DEFAULT 'UNNAMED'` column and a Java field initializer.
   Keep the explicit default: the journey below verifies that a client omitting
   the new field receives and persists `UNNAMED`. Do not infer a non-null constraint
   or enforcement of the OpenAPI length from this migration.
5. Export again in Step 8, then open **Regeneration preview**. Review the additive
   `Account.nickname` change and migration. If anything is unsafe/destructive,
   **stop**; do not edit approved hashes or remove a blocker to force success.
6. Approve/apply the displayed fresh plan. If files changed after preview, refresh
   and review again: stale approval is deliberately refused.

## Verify preservation and changed behavior

Save Project again and open the newly downloaded JSON file:
apply refreshes `last_generated_package_ref` to a new managed directory. Resolve
it against the same session workspace to find the **new** `MANAGED_APP`, not the removed previous path.
Verify `AccountService.java` is byte-identical to your customized file, generated
`AccountServiceBase.java` changed, and a new additive migration adds `nickname`
with default `UNNAMED`. This is preservation of the documented seam, **not** a
promise to retain arbitrary generated-file edits.

Run `mvn -B -ntp clean verify` again in the new directory; require executed tests
and zero failures/errors/skips. Start its JAR on loopback and repeat create/read,
adding `"nickname":"SYNTHETIC-NICKNAME"` to the request. Both responses must
retain `customerId: CUST-S8-HOOK` **and** return the new nickname. Also create a
second account with ID `ACCT-S8-DEFAULT`, omitting `nickname` entirely. Expect
201, then read it by that ID and expect 200; both responses must contain
`nickname: UNNAMED` and `customerId: CUST-S8-HOOK`. This proves the default for
clients that omit the field, not explicit-null behavior. Stop the app.
This exercises create and read-by-ID, not filtered lists, computed reads, EOD
delivery, authorization policies or persistent-database upgrade continuity.

## Repeatable proof and cleanup

The unchanged helper is for historical S8 reproduction with its recorded Studio
source and fixed Engine pair, available to authorized private-archive readers.
It enforces the Engine pin, not an arbitrary v5 selection, and records the Studio
SHA it actually runs. It is not the final browser acceptance driver. From that
clean historical Studio checkout with its own installed environment and JDK 17:

```sh
.venv/bin/python scripts/newcomer_journey.py \
  --engine-repo /path/to/pinned/EdgeForge \
  --work-dir /tmp/studio-newcomer-proof-UNIQUE
```

The output directory must not exist. The runner starts its own loopback Studio
server, uses real HTTP routes without injected sessions, invokes the real Engine,
and performs the explicit developer-file and terminal steps above. It also
confirms an actual stale plan is refused after a temporary developer-file edit.
It uses fresh state and a separate Maven cache. It does **not** observe a browser.
`receipt.json` records actual source pins, environment, requests/responses,
executed test counts and preservation hashes. Missing prerequisites, skipped
tests or an incomplete journey do not produce a pass. Raw logs and HTML may
contain local paths/session tokens: retain them locally, not in a public issue.

Troubleshooting: check the applicable Engine `.venv`, Java/Maven agreement, the selected
profile, output-under-workspace and the latest managed reference. A refused plan
is a safety result, not success. Preserve its diagnostics; do not bypass it.
Flyway may warn that this H2 minor is newer than its verified range; retain the
warning rather than interpreting passing tests as universal compatibility.

The runner stops its child apps and Studio server on completion/failure. For a
manual run, stop both Java and Studio. Remove only your own temporary proof/state
directories when no process uses them. Do not remove the source checkouts or
another session's data. Final selected Studio/Engine release revisions still need
applicability review and the relevant journey re-proof; this is not Suite acceptance.
