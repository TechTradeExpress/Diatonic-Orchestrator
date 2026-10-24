# Contributing workflow

Diatonic Orchestrator is developed through focused branches, tests and Pull Requests.

## Branches and Pull Requests

1. Branch from the latest `main` for each logical task. Use `feat/`, `fix/`, `test/`, `docs/`, or `chore/` prefixes with descriptive kebab-case names.
2. Keep PRs small and commits meaningful. Open a **Draft PR** while working, targeting `main`.
3. Fill in the PR template, explaining scope, validation and any impact on the public Resource Model.
4. Run `uv sync --group dev`, `uv run ruff check .`, and `uv run pytest` before requesting review. The GitHub Actions CI workflow runs lint and tests on PRs.
5. The agent must **not** self-merge or enable auto-merge. The maintainer reviews changes and, if accepted, squash-merges them.
6. Never push changes directly to `main` or force-push `main`. Do not introduce out-of-scope provider execution or vendor-specific behavior in the core.

M1 compiler behavior remains the baseline. M2 work follows the proposed
`docs/milestone-2.md` and ADR-0009 in separately requested PR-sized increments,
after review of the applicable architecture decisions. M2.0 is documentation only.
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
