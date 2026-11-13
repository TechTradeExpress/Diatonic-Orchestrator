# ADR-0021: Dependency reproducibility and Python support

- **Status:** Accepted (policy); implementation staged.
- **Date:** 2026-11-13.
- **Evidence baseline:** `005238515ddeb24be322d42fb84d7981278eaf87`, after PR #59.
- **Tracking:** [Issue #60](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/60),
  historical [M2-AUD-004](../reviews/milestone-2-architecture-quality-review.md#m2-aud-004--p2-reproducibility-and-supported-version-evidence-are-limited).
- **Human decision:** Maintainer `su-17`, 2026-11-13: variant A (dev/CI lock,
  separate upgrade lane and staged Python compatibility policy) approved.
  [Issue #62](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/62)
  records that approval and authorizes stage 1 only.
- **Implementation:** Stage 1 introduces the committed lock and pinned baseline
  described in the [developer guide](../contributing-workflow.md#locked-development-and-ci-baseline).
  Upgrade/extra-Python lanes remain unimplemented pending separate assignment;
  policy acceptance is not completion of M2-AUD-004 or authorization for M3.

## Original proposal evidence (unchanged)

| Source at the baseline | Observed state, not a compatibility guarantee |
| --- | --- |
| [Project metadata](../../pyproject.toml) / [README setup](../../README.md#setup) | MIT CLI/library; distribution `diatonic-orchestrator`, import/CLI `diatonic`; `requires-python = ">=3.12"` and README says Python 3.12+. No upper bound. |
| Runtime dependencies | Pydantic `>=2,<3`, PyYAML `>=6,<7`, Typer `>=0.12,<1`, Rich `>=13,<15`. |
| Development dependencies | pytest `>=8,<10`, Hypothesis `>=6,<7`, Ruff `>=0.8,<1`, mypy `>=1,<2`, types-PyYAML `>=6,<7`; build backend Hatchling `>=1.25,<2`. |
| Tracked files / [.gitignore](../../.gitignore) | No tracked `uv.lock`, `pylock.toml`, requirements/constraints file or `.python-version`. `uv.lock` is not ignored; a generated local file is not a committed artifact. `.venv` and caches are ignored. |
| [Existing CI](../../.github/workflows/ci.yml) | Ubuntu only; `lint-and-test` installs Python 3.12, runs `uv sync --group dev --python 3.12`, then mypy, Ruff and pytest. No committed resolution is enforced. setup-uv uses `@v6` without a selected uv release; Python patch and runner image can move. |
| Update automation | No tracked Dependabot/Renovate configuration or scheduled upgrade workflow. Existing triggers are pull requests and pushes to `main`. |
| Static versus runtime coverage | mypy targets Python 3.12; this does not test any interpreter. Repository CI covers runtime 3.12, not every version permitted by metadata or other OS/architecture combinations. |

A fresh checkout resolves the declared ranges and generates a local lock on sync.
An existing lock influences later resolution; ordinary sync is not an upgrade
command. These are evidence limits, not demonstrated instability or newer-Python
incompatibility. The historical audit and other ADR dispositions stay unchanged.

## Options

| Policy | Determinism and compatibility evidence | Maintenance and supply-chain tradeoff |
| --- | --- | --- |
| **A. Commit one universal dev/CI `uv.lock`** | Reuse reviewed resolutions across Python/platform markers. One locked baseline lane is repeatable at the Python dependency level; extra locked interpreter lanes sample marker-specific environments. A separate upgrade lane is still necessary. Package consumers retain metadata ranges. | Review lock graph/artifact changes and resolve conflicts; versions can become stale. Reduces surprise dependency changes, but hashes/locking do not establish publisher trust or eliminate vulnerable packages. |
| **B. Deliberately float ranges** | Resolve afresh in CI, retain exact resolution/tool/interpreter evidence per SHA and replayable resolution artifacts; repeat before releases and test supported interpreters. Historical logs alone cannot recreate an environment, and artifact retention limits replay. | Less lock maintenance and earlier upstream breakage signals, but the same source SHA may resolve differently over time. More incident triage and continuous exposure to new releases; reproducibility needs an explicit snapshot/retention process. |

Neither policy proves all permitted dependency combinations, oldest allowed versions,
or hermetic builds. A Python lock alone does not freeze OS images, Python binaries,
uv, Actions implementations, isolated build-backend dependencies or artifact availability.

## Accepted policy (variant A; staged implementation)

The maintainer accepted **A plus an independent floating-upgrade lane**. Stage 1
implements the locked baseline; upgrade and compatibility lanes below are future
work requiring their own assigned tasks:

- Commit one generated universal `uv.lock` for repository runtime/dev environments;
  keep existing dependency ranges in published wheel/sdist metadata. Consumers
  install normally using [published dependency metadata](https://packaging.python.org/en/latest/specifications/pyproject-toml/#dependencies-optional-dependencies),
  without requiring uv or the repository lock. Do not replace public ranges with
  exact pins. Smoke-test an installed distribution outside the source tree so
  project lock/source imports cannot mask consumer issues.
- Keep `lint-and-test` as the stable locked Python 3.12 baseline. Proposed commands
  are `uv sync --locked --group dev --python 3.12` and `uv run --locked --python 3.12`
  followed by the existing mypy, Ruff and pytest arguments. Reject missing/stale
  locks rather than regenerate them in this lane; do not use `--frozen` to bypass
  freshness checks. Retain the same lock across admitted interpreter lanes.
- Select and record a uv release and interpreter patch for the reproducibility
  lane in a later implementation review; use that exact patch in the commands
  sketched above with `3.12`. Log OS/architecture and tool versions.
  Separate reviewed changes update them. Isolated build dependencies and moving
  runner images remain explicit limits, not claimed reproducible inputs.
- Run a weekly and manually invocable upgrade check after separate authorization:
  in an isolated checkout use `uv lock --upgrade`, then locked sync and all checks.
  Keep its candidate lock as evidence; it must not overwrite the baseline lock or
  silently commit, merge or widen ranges. Record failures visibly and open a scoped
  maintainer-coordinated update task; review routine updates at least monthly and
  triage credible security fixes promptly. No automatic merge or Issue assignment.
- Review direct/transitive versions, markers, artifact hashes/sources, advisories,
  license changes and test results before adopting a candidate lock. A resolution
  or vulnerability-check failure is evidence to investigate, not reason to disable
  checks. No new scanner/service is selected here. Lock rollback restores known
  inputs but does not certify their safety.
- Key dependency caches by lock/metadata, interpreter, OS/architecture and uv version;
  do not reuse a cached virtual environment as proof. Synchronize before checking
  and demonstrate a cold-cache run at migration. Caches improve speed, not authority.

The uv documentation describes [universal lockfiles](https://docs.astral.sh/uv/concepts/projects/layout/#the-lockfile)
and [freshness checks and explicit upgrades](https://docs.astral.sh/uv/concepts/projects/sync/).
The lane split above is this project's proposed choice, not a uv requirement.

## Accepted Python policy (implementation deferred)

Keep `>=3.12` unchanged now. The accepted policy calls for minimum-plus-newest-stable
CPython checks on PRs once implemented, with a release-time sweep of intervening stable minor versions
still supported upstream. Use the same lock with its applicable Python markers;
record the resolved environment separately for each interpreter. No platform or
alternative-interpreter support is established by these Linux tests.

At implementation, identify the newest stable version using the
[official Python lifecycle table](https://devguide.python.org/versions/), record the
chosen minor/patch, and first run the full suite and an installed-wheel smoke test.
Do not automatically move a CI alias to an untested release. If dependencies cannot
support it, record a visible compatibility gap and require a human decision rather
than silently narrow metadata or claim all `>=3.12` versions tested. Prereleases may
be an explicitly informational experiment, not an admitted supported runtime.

Admit each new stable minor only after normal dependency resolution, applicable
marker validation, full pytest and package smoke tests pass at an identified SHA;
then update the tested-version documentation and lane explicitly. Intermediate
versions require the same admission evidence; endpoint success alone proves none
of them. A release sweep must pass for every advertised tested minor before release,
or the maintainer must resolve/defer the release and document the gap.

Retirement requires a separately approved compatibility change, release notes and
at least one release's deprecation notice, considering upstream end-of-life and
user impact. Raising `requires-python`, changing classifiers/docs and moving the
minimum CI lane must be reviewed together; never drop a version merely to hide a
failure. Retain mypy's 3.12 static target while 3.12 is the declared minimum. Static
analysis and per-interpreter runtime evidence remain distinct. This accepted policy
for interpreting/testing the existing open-ended requirement is not new test evidence.

## Human decision and staged implementation

The human decision above accepts variant A and the compatibility/admission and
retirement policy. The earlier proposal delivery in Issue #60 and its merge did
not adopt it; the explicit decision recorded in Issue #62 did. Later policy
revisions still require human review. Approval of the overall strategy does not
authorize stages 2–3, infrastructure execution or broader milestone work.

Implementation is staged in the order below. Issue #62 authorizes stage 1 only;
its technical acceptance is distinct from completing the remaining stages:

1. **Reproducible baseline:** select tool/interpreter versions, generate/review the
   lock and migrate the existing job to locked sync/run. Acceptance: exact-head
   mypy/Ruff/pytest pass on Python 3.12 from fresh environments with cold and warm
   caches; repeated sync leaves lock bytes unchanged; missing/stale-lock probes
   fail without rewriting it. Inspect built metadata for unchanged consumer ranges
   and verify a fresh wheel install/import/CLI smoke outside the checkout.
2. **Upgrade evidence:** add the separate manual/weekly upgrade lane. Acceptance:
   run IDs bind source SHA, candidate lock diff and tool/environment versions;
   normal resolution, mypy/Ruff/pytest pass or actionable failure is recorded;
   baseline lock stays unchanged, and a controlled failure proves visibility
   without weakening the locked job. Candidate adoption requires a separate human
   reviewed PR with exact-head results, never auto-merge.
3. **Python compatibility:** admit the newest stable minor with marker and wheel
   evidence; add one additional PR runtime lane and a manually invoked release
   sweep for intermediates. Acceptance: normal sync/full pytest/package smoke pass
   per admitted minor at the exact head, results enumerate actual interpreter
   versions, and the original `lint-and-test` check remains intact. Document tested
   versions, coverage limits, new-version admission and approved retirement steps.

Stage 1 does not change consumer dependency metadata, branch rules or runtime/API
behavior. Stages 2–3 remain deferred; no upgraded-dependency lane, broader tested
Python promise or complete M2-AUD-004 remediation is claimed.
