# M1.5: Identity index and declared reference resolution

`resolve_resources(documents)` consumes an iterable of existing `LoadedDocument`
records. It uses `parse_resource` for strict schema validation, then resolves the
currently modeled references. No Resource Model semantics, API namespaces, YAML
policies or resource schemas change.

The entrypoint is `diatonic.compiler.references.resolve_resources`; the loader
does not import this module or depend on model parsing. A caller can pass
`load_yaml_files(paths)` directly, then inspect `result.resources[identity]` and
`result.references` without file access inside the resolver.

## Result and provenance

`ResourceIndex.resources` is a read-only mapping from exact canonical `Kind/name`
to `IndexedResource(resource, source)`, in input declaration order. Names remain
case-sensitive; the same name under different kinds is valid. SourceLocation
contains the supplied path, document index and document-root line/column. It
never implies that a field was located on that line. Provenance is not inserted
into decoded YAML or serialized Pydantic resources.

`ResourceIndex.references` is a tuple of ResolvedReference records with owner ID,
field path, target ID and owner source. The target ID indexes the same mapping,
including its provenance. These records identify declared links, not derived
execution dependencies or normalized IR. Repeated links retain their distinct
field paths; no deduplication or graph construction occurs.

Decoded data is deep-copied before parsing so nested extension data is also
detached from caller-owned input. Record fields and the index mapping are frozen;
Pydantic models remain mutable, consistent with the existing schemas. Consumers
must treat returned resources as a snapshot (mutating identity fields would make
the index stale). This is a small in-memory API intended for M1.6 consumption,
not a new portable serialization contract.

## Validation and error policy

Validation fails fast, without returning partial results:

1. In input order, validate each document and check for duplicate identities.
   An invalid document reports the first Pydantic error in Pydantic's own error
   order, including its code, message and field path. The union's synthetic kind
   prefix is removed from the path; discriminator failures point to `kind`.
   A syntactically valid identity is included
   when available, even if the spec/version/kind is unsupported; otherwise None.
2. A duplicate reports the later declaration as `source`, and the first as
   `related_source`. Even identical declarations or repeated file inputs fail.
3. Only after the entire index is valid and unique, inspect references in resource
   declaration order: `depends_on` list order, `lifecycle.stage`, VM placement,
   VM interface list order, VM image. Stop at the first missing target.

The exception ResourceResolutionError carries a frozen ResourceDiagnostic with
stable code `invalid_resource`, `duplicate_identity` or `missing_reference`, owner
identity when available, field path and provenance. Missing references include the
canonical target; duplicate diagnostics include both origins. Human-readable
messages and underlying Pydantic codes are details, not new compiler error codes.
Re-running identical input produces identical result and diagnostic ordering.

No link is resolved against a partial or ambiguous index. Consequently a later
schema/duplicate error precedes an earlier resource's missing-reference error.
Only the first issue is reported; callers correct it and retry. YAML syntax/read
errors remain the existing loader's responsibility.

## Reference meaning and boundaries

- `depends_on` resolves the exact canonical identity of a declared supported kind.
  Unsupported undeclared kinds (e.g. Service) fail as missing targets; no new kinds
  are introduced to satisfy a reference.
- `lifecycle.stage` stores a bare name and looks up `Stage/<name>` exactly. It is
  not rewritten in the resource data; stage defaults are not invented.
- VM placement, interface network and image references require Hypervisor,
  Network and Image respectively, enforced first by the unchanged schemas.
- A same-named different-kind declaration never satisfies a missing target.
  Forward and cross-file references work because lookup uses the complete index.
- Self-references and cycles are accepted here; cycle detection, scheduling,
  stage ordering, implicit dependency extraction, lifecycle checks, subnet/IP
  checks, providers, normalized IR and CLI validation remain out of scope.

The infrastructure example references undeclared platform/workloads stages.
Valid integration tests explicitly supply `tests/fixtures/reference-stages.yml`;
separate failure tests preserve and demonstrate the missing-stage behavior.
