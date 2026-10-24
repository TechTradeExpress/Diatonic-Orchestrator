# M2.1: Dependency facts and Stage assignments

`diatonic.compiler.dependencies.classify_dependencies(index: ResourceIndex)`
consumes the existing M1.5 resolved-reference sequence and returns `DependencyFacts`.
This implements ADR-0009 §1's reviewed classification subset, not its later graph,
Stage-order, lifecycle or provider proposals. It does not parse/resolve again or
read mutable Pydantic resource models. The YAML schemas, resolver, CLI and M1
normalized portable output are unchanged, as are both versioned API namespaces.

## Internal representation

- `dependencies`: tuple of frozen/slotted `DependencyFact` records. Each has
  `prerequisite_identity`, `dependent_identity`, `classification` (explicit or
  implicit), original owning `resource_identity` and exact tuple `field_path`.
  Direction is prerequisite → dependent; dependent and original owner agree for
  all supported current references.
- `stage_assignments`: tuple of frozen/slotted `StageAssignment` records, with
  original owner, target `stage_identity` and tuple field path. No rank/defaults
  or dependency semantics are inferred from an assignment.
- `sources`: read-only mapping from owner identity to detached frozen/slotted
  `DependencySource` (path, document index, root line/column). Each fact's owner
  indexes its source. Sources are separate from portable fact fields, never sort
  keys. Owners with no references generate no facts or source-map entries.

Each resolved reference yields one fact in exactly one of the two collections:

| Field path | Result |
| --- | --- |
| `depends_on[i]` | Explicit dependency on the exact target, including Stage targets |
| VM `spec.placement.target` | Implicit dependency on its resolved Hypervisor |
| VM `spec.interfaces[i].network` | Implicit dependency on its resolved Network |
| VM `spec.image.ref` | Implicit dependency on its resolved Image |
| `lifecycle.stage` | Separate Stage assignment to its resolved Stage |

Repeated targets are preserved. An explicit Network dependency and two interfaces
on that Network produce three facts, identified by owner and distinct field paths.
The model/resolver already ensure target identity/kind/existence; classification
uses these links without introducing another index or resolution implementation.

## Ordering and unexpected fields

Successful output is ordered by case-sensitive lexicographic owner identity. Within
an owner, explicit dependencies precede implicit references: depends_on numeric
index, placement, interface numeric index, image. Stage assignments are returned
separately in owner order. Neither target identity, source filename, document order,
Stage order nor hash iteration changes that policy. Integer indexes above 9 stay
integers and sort numerically. Meaningful list positions and repeated links remain
intact; no endpoint deduplication occurs.

Recognize only exact tuple shapes and string/int segment types, with nonnegative
integer list indexes. Booleans, floats, string indexes, extra/missing segments and
future unclassified fields fail explicitly. VM-specific paths on other owner kinds
also fail, preventing a future schema from accidentally inheriting VM dependency
semantics. No metadata, extension, lifecycle-phase, disk or provider link rule is
guessed. `DependencyClassificationError` exposes stable code
`unsupported_reference_field`, owner, target, offending path and root source.
Shape validation fails fast in sorted owner order, retaining M1.5 reference order
within an owner for error selection; no partial facts are returned. A non-index
argument raises TypeError.

## Snapshot boundary and M2.2 consumption

Results retain no mutable models, dictionaries or lists from inputs. Record fields
and field paths are immutable, collections are tuples, and the source map owns its
backing dictionary. Provenance fields are copied rather than exposing the older
non-slotted SourceLocation record. Equivalent portable fact projections compare
equal across layouts; full DependencyFacts equality includes actual provenance.

The input must be a successful, unmodified M1.5 result. Mutating a model after
resolution does not update its recorded links: callers making such changes must
resolve again. Classification deliberately reads only resolved records, not model
state, and never changes input YAML, the index or a preexisting normalized IR.

M2.2 can consume the fact tuples, group by prerequisite/dependent pair and retain
all origin fields while deduplicating graph edges. It must obtain the complete
vertex set (including isolated resources) from the existing resource index or IR;
this collection is not a graph. Cycles and self-references remain classified
normally. Graph construction, cycle detection, topology, Stage precedence,
providers and execution remain outside this increment.
