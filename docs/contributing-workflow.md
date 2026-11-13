# Contributing workflow

This is the canonical, currently active development workflow for Diatonic
Orchestrator. Coordination is manual; GitHub records Issues, PRs, review evidence
and merge state. ChatGPT coordinates tasks and independently reviews them, Codex
CLI implements explicitly assigned work, and the human maintainer alone merges.

`ChatGPT creates Issue → Human assigns Issue → Codex implements and creates Draft PR → ChatGPT reviews → ChatGPT accepts, closes Issue and marks PR ready → Human merges → ChatGPT verifies and starts the next cycle`

## 1. Issue preparation by ChatGPT

ChatGPT analyzes the current repository and relevant project documentation, proposes
one focused, independently reviewable task and creates its GitHub Issue through
authorized GitHub access. The Issue defines requirements, scope, exclusions,
acceptance criteria, expected validation, architectural constraints and dependencies.
Each implementation task should normally have one associated Issue. Issue creation
does not authorize infrastructure execution or changes outside its defined scope.

## 2. Manual assignment by the human maintainer

The maintainer explicitly selects an Issue and instructs Codex CLI to work on it.
There is no automatic Issue polling, scheduling, label admission or assignment.
Codex works only on the assigned Issue and must not select the next task or expand
scope without authorization. Explicit delivery restrictions take precedence over
the normal steps below: a local-only task must not commit, push or create a PR.

## 3. Implementation by Codex CLI

1. Read [AGENTS.md](../AGENTS.md), the assigned Issue and relevant documentation;
   inspect the current implementation and tests before editing.
2. Branch from current `main` for the assigned task using a descriptive kebab-case
   name with `feat/`, `fix/`, `test/`, `docs/` or `chore/` prefix.
3. Implement only the authorized scope, keeping one logical task per PR.
4. Run appropriate tests and relevant checks using the
   [locked baseline commands](#locked-development-and-ci-baseline) below.
   Investigate failures and disclose any checks that could not run.
5. Commit focused changes with explanatory messages, publish the feature branch
   and open a **Draft PR** targeting `main` as soon as the scope is reviewable.
   Fill in the PR template with scope, validation and Resource Model/API impact.
6. Link the explicitly assigned Issue using a non-autoclosing reference such as
   `Refs #N`, rather than `Closes #N`; Issue closure happens at technical acceptance.
7. Report the PR URL, exact full head commit SHA, changed files, executed checks
   and outstanding limitations to the maintainer for independent review.

Codex must never push directly to `main`, merge its own PR, enable auto-merge,
close its task Issue or mark its own PR accepted or ready to merge.

## 4. Independent technical review by ChatGPT

The maintainer provides the Draft PR to ChatGPT. In a reviewing context independent
of implementation, ChatGPT reviews the original Issue and acceptance criteria,
complete PR diff, relevant implementation/tests, architecture and public API
compatibility, security boundaries, scope compliance and available CI results.
The review identifies the exact full PR head SHA and records findings and check
evidence in the GitHub PR conversation when authorized.

Review outcomes are:

- `CHANGES_REQUESTED`: Codex addresses the findings and updates the PR within scope.
- `ACCEPTED`: implementation satisfies the defined acceptance criteria.
- `BLOCKED`: missing evidence, permissions or required checks prevent completion;
  record what is missing and await human coordination.

Every new commit invalidates previous technical acceptance until the updated head
is reviewed. Re-read the current head before publishing review evidence; if it
changed, identify earlier findings as historical and review the new head.
ChatGPT technical acceptance, including a GitHub `COMMENT`, is distinct from a
formal GitHub `APPROVE` review and does not replace human merge authority or any
applicable architectural/human signoff. The coding agent cannot provide its own
independent acceptance.

## 5. Acceptance and Ready to Merge

After independent ChatGPT acceptance, ChatGPT completes these steps through
authorized GitHub access:

1. Verify the reviewed full head SHA is still current, required CI checks pass
   for that head and applicable acceptance criteria are satisfied.
2. Publish an explicit PR acceptance comment containing `ACCEPTED`, the full SHA,
   check evidence and `READY TO MERGE`.
3. Comment on the associated Issue that implementation at that SHA was accepted
   and is awaiting human merge, link the PR and close the Issue.
4. Mark the Draft PR **Ready for review**, removing Draft status. Leave it open.

If permissions or evidence are missing, report `BLOCKED` and any incomplete
transitions; do not claim completion. `READY TO MERGE` is a workflow decision,
not a GitHub merge action or a guarantee that branch rules are satisfied.

**Implementation accepted and Issue closed** is distinct from **PR merged into
`main`**. Never report an unmerged PR as merged. If an accepted PR is subsequently
rejected, abandoned or materially changed before merge, the maintainer and ChatGPT
must reconcile Issue/PR state, including reopening the Issue when necessary.
New commits always require fresh technical review and acceptance before merge;
remove stale readiness indicators while acceptance is pending.

## 6. Final merge by the human maintainer

The maintainer reviews the accepted PR and its current head, verifies that it still
matches the reviewed SHA, and confirms required GitHub checks and repository rules
pass. Only the human maintainer performs the final merge into `main` (prefer squash
merge after approval), then returns to ChatGPT with the merged PR information.
No agent may merge or enable auto-merge.

## 7. Next development cycle

After the maintainer reports the merge, ChatGPT verifies the actual GitHub merge
state and current `main`, confirms the merged changes are present and reviews the
resulting project state. It identifies the next appropriate development task and
creates the next Issue when authorized. There is no automatic task continuation;
the next implementation again requires explicit human assignment.

## Architecture and branch protection

M1 compiler behavior remains the baseline. For implemented M2 behavior and its
original incremental scope and acceptance baseline, see the
[Milestone 2 roadmap](milestone-2.md). Changes require separately scoped PRs and
review of applicable architecture decisions. M2.0 remains documentation only.
M2 analysis must remain offline: no provider/mock execution, provider protocol,
runtime scheduling, state/journal engine, or plan/apply. Preserve unspecified
lifecycle ownership and the existing Resource Model/API contracts.

## Agent kickoff

Read `AGENTS.md`, `docs/resource-model/v0alpha1.md`, `docs/decisions/0001-project-naming.md`, and `docs/milestone-1.md` before editing; for M2 also read `docs/milestone-2.md` and ADR-0009. The resource model takes precedence over implementation guidance. Begin with the smallest unit of work that can be independently reviewed, with focused tests. Discuss ambiguities in a PR rather than assuming a change to the public contract.

## GitHub ruleset (maintainer action)

The policies above are instructions, not technical enforcement. A maintainer should go to **Settings → Rules → Rulesets** and create an active ruleset for `main` with:

- Require a pull request before merging (at least one review approval, if the plan and repo settings support it).
- Require status checks to pass before merging: `lint-and-test` (select it after the first workflow run).
- Prevent force pushes and deletion of the default branch, with no bypass for the coding agent.
- Restrict direct updates to `main` as appropriate.

Verify that the ruleset is active. Agent instructions and CI alone cannot protect a branch.

## Locked development and CI baseline

[ADR-0021 variant A](decisions/0021-dependency-reproducibility-python-support.md) was
accepted by maintainer `su-17` on 2026-11-13; [Issue #62](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/62)
authorizes only its first implementation stage. Use **uv 0.13.8** and **CPython
3.12.16** for the reproducible development/CI baseline:

```sh
uv python install 3.12.16
uv sync --locked --group dev --python 3.12.16
uv run --locked --python 3.12.16 mypy src/diatonic
uv run --locked --python 3.12.16 ruff check .
uv run --locked --python 3.12.16 pytest
```

Commit `uv.lock`; ordinary sync/run must validate it rather than upgrade it.
After an intentional metadata/dependency change, maintainers generate and review a
new lock with the pinned uv release and commit it with exact-head check results.
An intentional `uv lock --upgrade` (or targeted `--upgrade-package`) belongs in a
separately reviewed update task; it is not part of ordinary CI. The separate
weekly/manual upgrade lane and additional Python compatibility lanes remain
unimplemented and require new assignments. Consumer wheel/sdist dependencies
retain their ranges and `requires-python = ">=3.12"`; consumers need no project lock.

The existing `lint-and-test` job pins these tool/interpreter versions, starts with
an empty dependency cache and fresh `.venv`, then repeats locked sync using the
warm cache. It checks unchanged lock hashes, mypy, Ruff and pytest. The CI-only
[verification helper](../.github/scripts/verify_locked_baseline.py) rejects missing
and stale locks in disposable copies without rewriting them or executing the
requested command, checks wheel/sdist consumer metadata and smoke-tests a fresh
wheel install/import/CLI version/help outside the source checkout. To repeat the
probes and packaging checks locally with the baseline environment:

```sh
uv run --locked --python 3.12.16 python .github/scripts/verify_locked_baseline.py
```

Cross-run cache restoration is disabled; the cold/warm evidence is generated in
each job. OS/architecture and uv/Python versions are logged. `ubuntu-latest`, the
runner image/kernel, Actions implementations, build-isolated Hatchling/backend
resolution, and network/artifact availability remain unfrozen: this is reproducible
Python dependency selection, not a hermetic build. Lock markers for other Python
versions/platforms do not establish tested compatibility. Mypy still targets 3.12;
no later-stage coverage or full audit remediation is claimed.

## Static typing baseline

Use the locked commands above to check the existing offline core.

`[tool.mypy]` in `pyproject.toml` targets Python 3.12 syntax/types and the complete
`src/diatonic` package (including models, compiler and CLI). It checks bodies of
untyped functions and warns about unused suppressions and redundant casts. This
is an incremental baseline, not strict mode or a typing requirement for tests.
No modules, missing imports or error categories are globally suppressed. PyYAML
requires the `types-PyYAML` development dependency; mypy does not replace Pydantic's
runtime validation. No Pydantic mypy plugin is enabled.

The baseline was measured on `ae3e9377c3e8fde5ca8f3d4f37c04a6e35bb9072` with
Python 3.13.5, mypy 1.20.2 and Typer 0.29.1: **35 errors in 14 files** before fixes,
including missing YAML stubs. These are measured versions, not a new version-support
or dependency-locking policy. The type-only Typer imports match that version's
vendored Click backend; runtime imports retain the external-Click fallback for
older supported Typer releases. Type-checking with an older Typer backend is not
claimed by this baseline. The existing GitHub Actions `lint-and-test` job installs
CPython 3.12.16 and the locked dev dependencies with uv 0.13.8,
then runs the named `Mypy` step with the locked command above, alongside Ruff and
pytest on pull requests and pushes to `main`. CI installs locked dependencies
without a custom `MYPYPATH` or staged stubs. The job name is unchanged;
repository branch-protection settings are managed separately by the maintainer.

Eight localized, error-specific suppressions preserve existing runtime contracts:

- `model/{stage,network,hypervisor,image,virtual_machine,provider,provider_binding}.py`:
  one `assignment` suppression on each concrete `spec` field. Pydantic replaces
  the envelope's optional JSON mapping with the required typed spec for that kind.
  Mypy treats this as incompatible mutable attribute inheritance. Broadening the
  base schema or making these models generic would change an existing public
  contract; these suppressions retain both schemas unchanged. Consumers must narrow
  to the concrete resource kind before accessing its kind-specific spec fields.
- `compiler/loader.py`: one `arg-type` suppression on `Composer.compose_node`.
  PyYAML actually passes `None`, integer sequence positions and mapping-key Nodes
  as its index; its stub only allows `int`. The override retains `object` and
  forwards the value unchanged. Assertions narrow composer results only where
  composition or `check_data()` already guarantees a Node.

All suppressions have inline explanations; there are no new casts or blanket
ignores. Keep the checks local to those exact incompatibilities and remove them
if the underlying typing contracts are corrected, without weakening validation.

## Deferred automated runner

The [Workflow MVP contract](development/agent-workflow-mvp.md) is
**FUTURE DESIGN / NOT THE CURRENT ACTIVE WORKFLOW**. It preserves historical and
prospective architecture for label admission, a trusted local runner, mutex,
checkpoints, recovery and automatic review coordination. None is implemented or
required by the current manual workflow. Implementing or adopting that model
requires a separate approved task and explicit migration decision; its detailed
technical contract is not reinterpreted by this guide.

Applicable architecture decisions and security constraints remain unchanged. The
[M3.2 entry packet](reviews/m3-synthetic-implementation-entry-gate.md) and
ADR-0018–0020 retain their separate human decision gates; documentation merge does
not authorize M3.3, provider execution, infrastructure operations or automation.
No labels, triggers, repository settings or permissions are changed by this guide.
