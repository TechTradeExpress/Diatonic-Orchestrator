# ADR-0011: Immutable logical dependency graphs and cycle witnesses

## Scope and API

`diatonic.compiler.graph.build_dependency_graph(index: ResourceIndex,
facts: DependencyFacts) -> DependencyGraph` consumes successful, unmodified M1.5
and M2.1 results. It implements the graph subset of ADR-0009, using ADR-0010's
classification. This is an internal offline analysis API, not an execution plan
or a new versioned serialization format. The normative Resource Model and both
API namespaces remain unchanged.

Every key in `index.resources` becomes a vertex, including isolated resources and
Stages. Direction is **prerequisite → dependent**. Edges are deduplicated by exact
ordered endpoint pair; each edge retains every original `DependencyFact` reason.
Repeated depends_on entries and multiple interfaces remain independently
identifiable by owner and exact field path, with integer indexes intact.

`lifecycle.stage` remains a separate `stage_assignments` tuple. Explicit depends_on
references to Stages are real edges. Neither Stage order nor lifecycle ownership,
desired state or execution phases are interpreted here. The resolver, normalized
IR and existing `diatonic validate` behavior remain unchanged, including their
acceptance of cycle-shaped declarations.

## Representation and ordering

The frozen/slotted `DependencyGraph` contains:

- `vertices`: case-sensitive lexicographically sorted identity tuple.
- `edges`: unique `DependencyEdge` records sorted lexicographically by
  `(prerequisite_identity, dependent_identity)`.
- `successors`: owned read-only mapping for **every** vertex, with sorted unique
  successor tuples (empty for sinks and isolated vertices).
- `sources`: owned read-only identity-to-`DependencySource` mapping for every
  vertex, detached from the index. Values contain source path, document index and
  available document-root line/column, never fabricated field coordinates.
- `stage_assignments`: copied records sorted by owner identity.

Each edge's `reasons` tuple orders explicit before implicit, then owner identity,
then ADR-0010's category ordering: depends_on, placement, interfaces, image.
Within a category, field-path segments compare by value, with integer list indexes
compared numerically (2 before 10). Current reasons on one edge share an owner;
category ordering preserves M2.1's original reference-list semantics. No filename,
declaration order, Stage rank or hash iteration determines portable graph order.

All retained records and paths are immutable, maps own their backing dictionaries,
and no Pydantic model or mutable input collection survives in the result. Mutating
YAML data or models after construction cannot alter it. Sources stay separate
from portable facts: compare vertices, edges, successors and Stage assignments for
layout-independent equality; full graph equality intentionally includes provenance.

## Input consistency and failure policy

Inputs must come from matching successful resolver/classification runs; changing a
model after resolution does not update recorded links, so callers must resolve
again. The builder checks indexed identity agreement, known endpoints/owners,
owner/dependent agreement, required provenance and its agreement with the index,
and dependency/Stage category compatibility. It compares reference and fact
multiplicities by `(owner, field_path, target)`, detecting dropped, added or altered
links without re-parsing or resolving anything. This is a consistency guard, not
a replacement schema validator or a general validation framework.

An inconsistency raises `DependencyGraphInputError` with stable code
`invalid_graph_input`, a reason and an owner identity when available. Checks fail
fast: sorted index identities first, then supplied source/fact/reference sequences.
No canonical ordering guarantee is made for diagnostics from arbitrarily corrupted
external objects. Wrong top-level argument types raise TypeError. No successful
partial graph is returned after either an input error or a cycle.

## Cycle algorithm and diagnostics

After grouping edges, iterative depth-first search inspects roots and successors
in sorted identity order. An explicit stack and active-path position map avoid
Python recursion limits on long chains. The first edge to an active ancestor
selects the cycle; edges to finished vertices are skipped. Rotate that directed
cycle to start at its smallest identity, then append the start to close it.
Never reverse direction. A self-edge yields `(X, X)`.

`DependencyCycleError` has stable code `dependency_cycle` and a frozen/slotted
`diagnostic` containing the closed `witness`, its ordered `edges` with **all**
reasons, and detached `sources` for all witness endpoints (also covering every
reason owner). Its human-readable message includes direction, classifications,
owner identities, exact tuple paths and document-root origins. Example:

```text
dependency_cycle: Stage/a -> Stage/b -> Stage/a;
Stage/a -> Stage/b: explicit owner=Stage/b field=('depends_on', 0)
at resources.yml (document 2, root line 8, column 1); ...
```

Only one witness is reported, not every cycle. Traversal is O(V + E) after
canonical sorting; origin retention also scales with the number of references.

## M2.3 boundary

M2.3 can consume the cycle-checked vertices, adjacency, edge origins, Stage
assignments and full provenance. Stage ranks must be read from a compatible
validated resource snapshot/index separately: this graph intentionally stores no
mutable resource models and assigns no ranks. Stage precedence/conflicts and
any topological ordering require their own reviewed implementation. Providers,
phase scheduling, deletion reversal, state and execution remain outside this API.
