# M1.6: Immutable normalized intermediate representation

`diatonic.compiler.normalize.normalize_resources(index: ResourceIndex)` consumes
the successful M1.5 result. It returns an internal `NormalizedIR`, without file
access, schema/index rebuilding, reference resolution or execution semantics.
Neither Resource Model API namespace nor existing model/loader behavior changes.

## Structure and portable export

- `resources`: read-only mapping of exact `Kind/name` to `NormalizedResource`.
  Each frozen resource record contains its identity and detached canonical JSON
  text, with `to_dict()` and `to_json()` exporters. No Pydantic models are retained.
- `references`: tuple of frozen `NormalizedReference` records containing owner
  `resource_identity`, tuple `field_path` and `target_identity`. They describe
  declared links, not execution edges. Repeated links are retained.
- `sources`: separate read-only identity-to-`NormalizedSource` mapping retaining
  actual source paths, document indexes and document-root line/column. Existing
  source fields are copied into frozen, slotted records; coordinates are not field marks.

`ir.to_dict()` returns the following JSON-compatible internal shape:

```json
{
  "references": [
    {"field_path": ["lifecycle", "stage"],
     "resource_identity": "VirtualMachine/app", "target_identity": "Stage/workloads"}
  ],
  "resources": {
    "Stage/workloads": {"api_version": "iac/v0alpha1", "kind": "Stage",
                        "metadata": {"name": "workloads"}, "spec": {"order": 40}},
    "VirtualMachine/app": {"api_version": "iac/v0alpha1", "kind": "VirtualMachine",
                           "metadata": {"name": "app"},
                           "spec": {"cpu": {"cores": 1}, "memory": {"mib": 512}},
                           "lifecycle": {"stage": "workloads"}}
  }
}
```

This is not a new user-facing Resource Model or versioned provider protocol.
Sources are never included in either portable export. IR object equality includes
the separate source map; compare portable exports for equivalence across layouts.

## Canonicalization and declared values

Resources and source-map keys use case-sensitive Python lexicographic identity
order. References use sorted owner identities followed by the unchanged M1.5
within-owner order: explicit dependencies, stage, placement, interfaces, image.
The stable sort preserves integer list indexes (including indexes above 9) and
distinct field paths; targets are not sorted or deduplicated. Disk, interface,
dependency and extension arrays retain their declared order.

Resource snapshots use `model_dump(mode="json", exclude_unset=True,
warnings="error")`. Omitted model fields and their implicit defaults stay omitted
at every depth. Explicit nulls, empty collections, false, zero and explicitly set
defaults are retained. An omitted lifecycle remains omitted; no phase ownership
or destruction policy is invented. An explicit empty lifecycle object stays `{}`.
Metadata, portable specs, dependencies and `extensions.<platform>` are preserved.
Mapping keys are recursively sorted in JSON text; export dictionaries inherit
that deterministic order. JSON uses compact separators and literal Unicode, and
rejects non-finite numbers rather than emitting nonstandard JSON. No IP strings,
names, case or values are normalized beyond existing JSON-mode serialization.

## Snapshot and consistency boundary

Frozen, slotted records store resource snapshots as strings rather than exposing
live nested dictionaries/lists. This keeps the implementation small without an
immutable-object framework. Index/source mappings own their backing dictionaries;
reference collections and field paths are tuples. Every `to_dict()` call creates
new nested containers. Mutations to loaded YAML, M1.5 models or exported data
cannot change an existing snapshot. No hashes, state or generated files are used.

Before serialization, each key must match `entry.resource.identity`; otherwise
`NormalizationError` reports code `identity_mismatch`, both identities and source.
Checks run in sorted identity order and return no partial IR. Non-ResourceIndex
arguments raise TypeError. Serialization failures are explicit exceptions, not
fallback conversions. The input is expected to be a successful, otherwise
unmodified M1.5 result: this step does not revalidate schemas or recompute links
after arbitrary caller mutations. Callers changing references before normalization
must run M1.5 again. Concurrent mutation during normalization is unsupported.

DAG/cycle handling, scheduling, provider resolution/execution, network semantics,
configuration hashing, on-disk state and CLI commands remain out of scope.
