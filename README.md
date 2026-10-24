# Diatonic Orchestrator

**Provider-agnostic Infrastructure as Code Orchestrator**, developed by **TechTradeExpress**. MIT licensed.

> Infrastructure should describe what a resource is and what state is desired, not which tool happens to create it.

Diatonic Orchestrator is an early-stage open-source project. It aims to provide a portable logical resource model with provider-independent lifecycles and deterministic compilation. It does **not** replace Terraform/OpenTofu, Ansible, or vendor APIs.

## Status

The Milestone 1 compiler pipeline and `diatonic validate` CLI are implemented:
strict YAML loading, typed resource schemas, canonical identities, declared
reference resolution, network-scoped IPv4 semantic checks and immutable normalized
IR. Supported resource kinds are `Stage`, `Network`, `Hypervisor`, `Image` and
`VirtualMachine`.

Validation covers the implemented declaration checks below. Broader semantic
conditions in the design document remain future work; this does not assert that
every Milestone 1 semantic acceptance criterion has been completed.

M2 dependency classification, immutable cycle-checked graphs, offline Stage
constraints and deterministic topological analysis are implemented, together with
`diatonic graph`. Offline capability/provider resolution and `diatonic explain`
remain planned in the [Milestone 2 roadmap](docs/milestone-2.md). See
[ADR-0012](docs/decisions/0012-stage-order-analysis.md) for the internal Stage
policy. Provider execution, protocols and destructive operations remain outside M2.

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
- Network gateway membership in its declared IPv4 CIDR, static VM host membership
  in its referenced Network, duplicate static hosts within the same logical
  Network, and VM addresses conflicting with that Network's gateway. Interface
  prefix lengths need not match the Network prefix. Optional IPv4 blocks remain
  optional; no addresses are synthesized.
- Conversion of the resolved index to the existing immutable normalized IR.

Success prints resource and resolved declared-reference counts to stdout and exits
`0`. Configuration errors print the first diagnostic to stderr and exit `1`;
missing arguments or unknown options use conventional Typer usage errors (`2`).
Schema/reference/semantic diagnostics identify a document-root location and a
field path;
the root coordinates are not exact field locations. Duplicate identities show
both declarations; duplicate IPv4 diagnostics include both owners and field paths.
File/decoding errors have only the source information available.
Diagnostic text is rendered literally, including bracketed names and paths.

For the full infrastructure example, explicitly include the Stage fixture:

```sh
uv run diatonic validate examples/infrastructure/resources.yml tests/fixtures/reference-stages.yml
```

The infrastructure example alone is intentionally incomplete: it references
`Stage/platform` and `Stage/workloads` without declaring them.

The command does not check cycles/DAG ordering, provider availability, cross-network
topology/collisions or lifecycle policies. Duplicate IPs on different logical
Networks are allowed, even when their CIDRs overlap. No network/broadcast address
reservation policy is inferred beyond the declared gateway conflict check.
A successful result establishes the checks listed above, not complete
infrastructure semantics. Broader checks require follow-up work. Validation reads
input files and produces no state or generated IR files. Provider execution,
`plan`, `apply`, JSON output and IR export commands are not implemented.

## Inspect the logical graph

```sh
uv run diatonic graph examples/minimal/stages.yml examples/minimal/resources.yml
```

```text
Logical dependency graph (offline, not an execution plan)
Resources: 2; dependency edges: 0; declared reasons: 0; Stage assignments: 1

Vertices (2):
  Stage/workloads
  VirtualMachine/docker01

Dependencies (0):
  (none)

Stage assignments (1):
  VirtualMachine/docker01 -> Stage/workloads (order=40)

Topological order (2):
  1. Stage/workloads
  2. VirtualMachine/docker01
```

`diatonic graph FILE [FILE ...]` accepts explicit files and multi-document YAML,
with forward and cross-file references. Include all referenced resources. For the
full infrastructure example:

```sh
uv run diatonic graph examples/infrastructure/resources.yml tests/fixtures/reference-stages.yml
```

A dependency arrow means **prerequisite → dependent**: `Network/servers ->
VirtualMachine/app` means the Network is a prerequisite of the VM. Explicit
`depends_on` and implicit VM placement, interface-network and image references
produce dependency edges. Each unique edge lists every original reason with its
explicit/implicit classification, owner and field path, including repeated
references and numeric list indexes.

Stage assignments are shown separately and create no dependency edge. An explicit
`depends_on: [Stage/workloads]` does create an edge to its dependent. Under the
internal offline Stage policy, all members assigned to a lower numeric order
precede all members assigned to a higher order. Equal numeric orders add no
precedence. Unassigned resources keep no rank or default, including Stage
vertices unless explicitly assigned themselves. The topological order chooses the
smallest case-sensitive currently eligible identity, respecting dependencies and
Stage groups; unassigned vertices may appear before, between or after groups.

`graph` performs the same M1 declaration checks as `validate`, then additionally
rejects dependency cycles and direct or indirect backwards Stage paths (including
unassigned intermediates). `validate` retains its declaration-only behavior and
continues to accept otherwise valid cyclic or Stage-conflicting declarations.
Neither command checks every infrastructure semantic condition.

Graph success uses stdout only and exits `0`. Expected errors use stderr only and
exit `1`, without partial graph output; usage errors exit `2`. Cycle diagnostics
include a closed directed witness and all edge reasons. Stage conflicts show the
dependency path and both Stage assignments/orders. Sources in diagnostics refer
to document roots, not exact field positions. Successful output omits source
filenames, follows canonical graph ordering, and prints `(none)` for empty
sections. Names and diagnostic paths render literally, without Rich markup.
Empty YAML files remain invalid; missing file arguments remain usage errors.

This is a read-only, provider-free offline view. It does not initialize providers,
execute infrastructure operations, generate graph/IR files, manage state or
journals, perform planning or deployment, or produce an execution/deletion plan.
There are no JSON, DOT or Mermaid exporters, `plan`, `apply` or `explain` commands.

## Project documents

- [`docs/resource-model/v0alpha1.md`](docs/resource-model/v0alpha1.md): normative architecture/design proposal, source of truth for the project.
- [`docs/decisions/0001-project-naming.md`](docs/decisions/0001-project-naming.md): naming decision and API namespace policy.
- [`docs/milestone-1.md`](docs/milestone-1.md): first implementation steps and acceptance criteria.
- [`AGENTS.md`](AGENTS.md): coding agent constraints and workflow.

## Names and compatibility

Project: **Diatonic Orchestrator**; Python distribution: `diatonic-orchestrator`; module and CLI: `diatonic`. YAML resource model remains `api_version: iac/v0alpha1` and external provider protocol remains `iac-provider/v0alpha1`. Product naming is intentionally independent of versioned APIs.

## License

MIT. Copyright (c) 2026 TechTradeExpress.
