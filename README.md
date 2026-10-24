# Diatonic Orchestrator

**Provider-agnostic Infrastructure as Code Orchestrator**, developed by **TechTradeExpress**. MIT licensed.

> Infrastructure should describe what a resource is and what state is desired, not which tool happens to create it.

Diatonic Orchestrator is an early-stage open-source project. It aims to provide a portable logical resource model with provider-independent lifecycles and deterministic compilation. It does **not** replace Terraform/OpenTofu, Ansible, or vendor APIs.

## Status

The Milestone 1 compiler pipeline and `diatonic validate` CLI are implemented:
strict YAML loading, typed resource schemas, canonical identities, declared
reference resolution and immutable normalized IR. Supported resource kinds are
`Stage`, `Network`, `Hypervisor`, `Image` and `VirtualMachine`.

Validation covers the implemented declaration checks below. Broader semantic
conditions in the design document remain future work; this does not assert that
every Milestone 1 semantic acceptance criterion has been completed.

## Setup

Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) are required.

```sh
uv sync --group dev
uv run diatonic --help
uv run diatonic --version
uv run pytest
uv run ruff check .
```

`uv sync` creates the local environment and generates `uv.lock` if it is absent.

## Validate resource declarations

From the repository root:

```sh
uv run diatonic validate examples/minimal/stages.yml examples/minimal/resources.yml
```

The command accepts one or more explicit paths (`diatonic validate FILE [FILE ...]`)
and reads all YAML documents in each file. Files are processed in argument order;
references can point forward or across files. There is no directory scanning or
implicit configuration path. Supply all referenced resources, including stages.

It checks:

- Strict safe YAML parsing, duplicate keys, string mapping keys and mapping roots.
  Empty documents, unsafe tags, aliases and merge keys are rejected.
- Supported API versions/kinds, required fields, strict types, unknown fields and
  the existing schemas' basic IP/CIDR and reference-kind syntax checks.
- Unique `Kind/name` identities and existence of declared dependencies, lifecycle
  stages, VM placement targets, interface networks and image references.
- Conversion of the resolved index to the existing immutable normalized IR.

Success prints resource and resolved declared-reference counts to stdout and exits
`0`. Configuration errors print the first diagnostic to stderr and exit `1`;
missing arguments or unknown options use conventional Typer usage errors (`2`).
Schema/reference diagnostics identify a document-root location and a field path;
the root coordinates are not exact field locations. Duplicate identities show
both declarations. File/decoding errors have only the source information available.
Diagnostic text is rendered literally, including bracketed names and paths.

For the full infrastructure example, explicitly include the Stage fixture:

```sh
uv run diatonic validate examples/infrastructure/resources.yml tests/fixtures/reference-stages.yml
```

The infrastructure example alone is intentionally incomplete: it references
`Stage/platform` and `Stage/workloads` without declaring them.

The command does not check cycles/DAG ordering, provider availability, IP collisions,
subnet membership or lifecycle policies. A successful result establishes syntax,
schema, identity and declared-reference validity, not complete infrastructure
semantics. These broader checks require follow-up work; no new semantic rules are
added by the CLI. Validation reads input files and produces no state or generated
IR files. Provider execution, `plan`, `apply`, JSON output and IR export commands
are not implemented.

## Project documents

- [`docs/resource-model/v0alpha1.md`](docs/resource-model/v0alpha1.md): normative architecture/design proposal, source of truth for the project.
- [`docs/decisions/0001-project-naming.md`](docs/decisions/0001-project-naming.md): naming decision and API namespace policy.
- [`docs/milestone-1.md`](docs/milestone-1.md): first implementation steps and acceptance criteria.
- [`AGENTS.md`](AGENTS.md): coding agent constraints and workflow.

## Names and compatibility

Project: **Diatonic Orchestrator**; Python distribution: `diatonic-orchestrator`; module and CLI: `diatonic`. YAML resource model remains `api_version: iac/v0alpha1` and external provider protocol remains `iac-provider/v0alpha1`. Product naming is intentionally independent of versioned APIs.

## License

MIT. Copyright (c) 2026 TechTradeExpress.
