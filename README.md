# Diatonic Orchestrator

**Provider-agnostic Infrastructure as Code Orchestrator**, developed by **TechTradeExpress**. MIT licensed.

> Infrastructure should describe what a resource is and what state is desired, not which tool happens to create it.

Diatonic Orchestrator is an early-stage open-source project. It aims to provide a portable logical resource model with provider-independent lifecycles and deterministic compilation. It does **not** replace Terraform/OpenTofu, Ansible, or vendor APIs.

## Status

**Starter repository — Milestone 1 (Resource Compiler) not implemented.** Only the CLI bootstrap (`--help`, `--version`), documentation, and smoke tests are included.

## Setup

Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) are required.

```sh
uv sync --group dev
uv run diatonic --help
uv run diatonic --version
uv run pytest
uv run ruff check .
```

`uv.lock` will be generated on the first successful online `uv sync` and should then be committed.

## Project documents

- [`docs/resource-model/v0alpha1.md`](docs/resource-model/v0alpha1.md): normative architecture/design proposal, source of truth for the project.
- [`docs/decisions/0001-project-naming.md`](docs/decisions/0001-project-naming.md): naming decision and API namespace policy.
- [`docs/milestone-1.md`](docs/milestone-1.md): first implementation steps and acceptance criteria.
- [`AGENTS.md`](AGENTS.md): coding agent constraints and workflow.

## Names and compatibility

Project: **Diatonic Orchestrator**; Python distribution: `diatonic-orchestrator`; module and CLI: `diatonic`. YAML resource model remains `api_version: iac/v0alpha1` and external provider protocol remains `iac-provider/v0alpha1`. Product naming is intentionally independent of versioned APIs.

## License

MIT. Copyright (c) 2026 TechTradeExpress.
