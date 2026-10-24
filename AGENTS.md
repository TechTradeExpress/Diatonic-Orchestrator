# Guidance for coding agents

You are working on **Diatonic Orchestrator**, a public MIT open-source IaC project by TechTradeExpress.

## Read first

1. Read `docs/resource-model/v0alpha1.md` entirely; it is the source of truth for architecture and semantics.
2. Read `docs/decisions/0001-project-naming.md`, `docs/milestone-1.md`, and `docs/milestone-2.md`; for M2 work also read ADR-0009.
3. Inspect existing tests and implementation before changing anything.

## Invariants

- Product name: **Diatonic Orchestrator**; distribution: `diatonic-orchestrator`; import module and CLI: `diatonic`.
- Do **not** change `iac/v0alpha1` or `iac-provider/v0alpha1` because of a product rename. API versions are separate public contracts.
- Python >=3.12; Pydantic 2, PyYAML, Typer, Rich, uv, pytest, Hypothesis, Ruff, and mypy (or pyright).
- Portable logical resources must not embed Terraform/Ansible/Proxmox implementation details.
- Platform-specific fields belong under `extensions.<platform>`, not `extensions.<engine>.<platform>`.
- Canonical identity: `Kind/name`. Validate before any execution. Deterministic results, explicit errors, no arbitrary fallback.
- Core must have no special-case `if proxmox`, `if terraform`, or `if ansible` branches.
- Atmos is the benchmark: do not recreate its generic YAML workflow/component features without compelling differentiation.

## Scope: M1 maintenance and incremental M2 work

Preserve the implemented M1 resource compiler, IPv4 checks, immutable IR and thin validate CLI. Use `docs/milestone-1.md` for that baseline and `docs/milestone-2.md` for proposed dependency/Stage analysis and offline provider resolution. Work only on the explicitly requested increment; M2.0 is documentation only, and subsequent implementation requires review of its applicable architecture choices.

M2 may add logical graphs/topological analysis, `Provider`/`ProviderBinding` schemas, capabilities, offline resolution and provider-free graph/explain views only in separately scoped tasks. **Do not** implement runtime scheduling, provider execution (including mock execution), provider protocol, real Terraform/Ansible/RouterOS/Proxmox integrations, state/journal handling, secret management, plan/apply, general templating or a GUI in M2. Preserve unspecified lifecycle values; do not infer destructive operations from desired state alone.

The Resource Model is public API; in-memory compiler representation can evolve independently. Changes to contract semantics require a documented rationale and tests. Where the design document leaves a decision open, select the narrowest safe behavior and document it rather than silently expanding scope.

## Working practice

- Use branches and small pull requests. The agent must not assume protected branch configuration is already active.
- Run tests and lint where dependencies are available; disclose any unrun checks.
- Do not commit credentials, real infrastructure endpoints, `uv` caches, `.venv`, or state files.
- Keep example YAML non-secret and vendor-neutral.

## GitHub collaboration workflow (mandatory)

1. Start from the current `main` on a dedicated branch named `feat/...`, `fix/...`, `test/...`, `docs/...`, or `chore/...`. Never commit or push directly to `main`.
2. Commit focused changes with explanatory messages; open a Draft Pull Request targeting `main` as soon as there is a reviewable task scope.
3. Keep one logical task per PR, ideally tied to a GitHub Issue; avoid combining unrelated milestone steps.
4. Include a short summary, exact tests executed or not executed, and any Resource Model/API impact in every PR.
5. Run `uv run ruff check .` and `uv run pytest` before asking for review; investigate failing CI checks rather than bypassing them.
6. Do **not** self-merge or enable auto-merge. The human maintainer reviews and chooses when to merge. Prefer squash merge after approval.
7. Do not silently change `iac/v0alpha1`, `iac-provider/v0alpha1`, or work beyond the requested milestone.

See `docs/contributing-workflow.md` for details.
