# Milestone 1: Resource Compiler

This is the implementation roadmap, not a change to the architecture. Read the Resource Model document first.

## Goal

Compile YAML documents to deterministic, validated logical resources. No provider execution, DAG or provider resolution.

## Suggested small commits

1. `chore: bootstrap project` — completed in this starter: packaging, CLI smoke tests, docs.
2. `feat(model): define resource envelope` — metadata, lifecycle, API version, canonical identity; tests.
3. `feat(model): add Stage and VM core specs` — typed models, discriminator, tests.
4. `feat(loader): implement strict YAML loading` — multiple documents, duplicate-key detection, source ordering and errors; tests.
5. `feat(model): complete infrastructure schemas` — Network, Hypervisor, Image and remaining VM fields; tests.
6. `feat(compiler): add identity and reference resolution` — cross-file index, missing/wrong-kind reference errors; tests.
7. `feat(compiler): produce normalized IR` — source metadata separate from portable resource model, stable results; tests.
8. `feat(cli): add diatonic validate` — CLI wrapping library compiler, helpful diagnostics, nonzero exit code on errors; tests.

The numbered items are implementation increments, not a requirement to implement multiple commits per pull request.

## Acceptance criteria

- Reads one/many YAML files and multi-document YAML independently of directory layout.
- Rejects malformed YAML, duplicate keys, unknown `api_version`, unknown kinds/fields and incorrect value types.
- Implements `Stage`, `Network`, `Hypervisor`, `Image`, `VirtualMachine` models from the public design document.
- Rejects duplicate `Kind/name` and invalid, missing or wrongly typed references.
- Performs basic semantic validation that can be proven from declared resources.
- Produces deterministic normalized intermediate representation with source locations kept separate from model data.
- Exposes a working `diatonic validate` command.
- Tests cover valid samples and failure cases.

## Audit-driven follow-up

M1.8 adds a separate IPv4 semantic validation step after reference resolution and
before normalized IR: gateway/subnet membership, static VM host membership,
duplicate static hosts within one logical Network and gateway conflicts. This
closes a specific declared-data validation gap from Resource Model §23; broader
lifecycle and topology semantics remain separate work. See decision 0008.

## Deferred to milestone 2+

Do not build DAG ordering, graph/explain commands, Provider/ProviderBinding resolution, protocol, mock providers, journal, or real adapters. No `plan` or `apply` commands in M1.
