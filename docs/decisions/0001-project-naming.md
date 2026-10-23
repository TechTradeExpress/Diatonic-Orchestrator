# ADR-0001: Adopt the Diatonic Orchestrator product name

- **Status:** Accepted
- **Date:** 2026-10-15
- **Owner/publisher:** TechTradeExpress

## Context

The project was originally described using the placeholder *IaC Orchestrator* and the `iac` CLI. An expressive independent open-source project name is useful while keeping the software's higher-level resource abstraction and provider-agnostic semantics unchanged.

## Decision

- Official project name: **Diatonic Orchestrator**.
- GitHub repository target: `TechTradeExpress/diatonic-orchestrator`.
- Python distribution: `diatonic-orchestrator`.
- Python import module and executable CLI: `diatonic`.
- License: MIT.
- **Resource Model API: `iac/v0alpha1` (unchanged)**.
- **Provider protocol API: `iac-provider/v0alpha1` (unchanged)**.

Product branding and public versioned API namespaces are distinct. Renaming the project is not sufficient technical justification for rewriting previously defined YAML contracts or provider protocol identifiers. Any future change requires a separate versioning decision.

## Consequences

- Usage will look like `diatonic validate` once the command is implemented.
- YAML files continue to begin with `api_version: iac/v0alpha1`.
- The package and examples should use the updated product name.
- Domain ownership, PyPI availability and trademarks must be independently checked before publishing; none are asserted as registered by this ADR.
