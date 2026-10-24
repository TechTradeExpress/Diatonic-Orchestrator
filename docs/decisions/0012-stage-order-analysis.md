# ADR-0012: Offline Stage constraints and deterministic topological analysis

## Authority and policy status

Resource Model v0.1 §§8–9 requires integer Stage orders and respecting dependencies
alongside Stage ordering. It does not specify equal orders, unassigned resources,
conflict selection or a deterministic sorting algorithm.

For **M2.3's internal implementation only**, Issue #24 accepts ADR-0009 §2's strict
ordered-group policy, subject to independent PR review. This decision records that
policy without changing the normative Resource Model, `iac/v0alpha1`, or
`iac-provider/v0alpha1`. Future alternative Stage semantics require separate review
and an ADR. These are offline analysis constraints, not lifecycle phase barriers
or a runtime execution schedule.

## API and immutable result

```python
from diatonic.compiler.stages import analyze_stage_order

analysis = analyze_stage_order(index, graph)
# index: ResourceIndex; graph: successful M2.2 DependencyGraph
identities = analysis.order
```

`StageOrderAnalysis` is frozen/slotted and contains:

- `order`: tuple containing every logical graph vertex exactly once.
- `stage_orders`: owned read-only mapping of all declared Stage identities to
  their current strict integer orders, including unused Stages.
- `assignments`: owned read-only mapping sorted by resource identity, containing
  frozen/slotted `RankedStageAssignment` records: owner `resource_identity`,
  `stage_identity`, snapshotted numeric `order`, original tuple `field_path`.
- `sources`: separate owned read-only mapping of every vertex to detached
  frozen/slotted document-root provenance (path, document index, available line
  and column). These coordinates are not exact locations of erroneous fields.

No mutable Pydantic models or writable input containers are retained. Subsequent
YAML or model edits cannot change completed analysis or diagnostic snapshots.
Portable comparisons use order, Stage orders and assignments; full equality also
includes real provenance. Filenames, declaration order and filesystem layout are
never portable ordering or witness-selection keys.

## Stage precedence and unassigned resources

Every explicitly assigned member of a lower numeric order must precede every
assigned member of a higher order. Negative, zero and positive orders are valid.
Different Stage names with the same order form one group; neither same-Stage nor
equal-order membership adds precedence between members. Real explicit/implicit
dependency edges still constrain those members.

An omitted/null Stage assignment stays unassigned. No rank is inherited from any
neighbor, and no zero/default Stage is invented. A Stage declaration's own
`spec.order` ranks its assigned members, **not that Stage vertex**. Only an explicit
lifecycle Stage assignment ranks a Stage vertex, using its target Stage's order.
Unused Stage declarations impose no constraints by themselves.

`lifecycle.stage` remains a separate rank assignment. An explicit
`depends_on: [Stage/x]` still means a real prerequisite on the Stage vertex.
M2.2 edges, reasons and successor adjacency remain untouched.

## Input boundary and controlled errors

The entrypoint requires a matching successful `ResourceIndex` and cycle-checked
M2.2 graph. It neither parses YAML, re-resolves references, classifies dependencies
again, nor constructs a second public graph. It checks:

- Exact vertex identities, identity/model agreement and full source agreement.
- Validated Stage model/spec with a strict integer order, known Stage targets,
  known assignment owners, exact assignment paths and no duplicate assignments.
- Agreement between recorded assignments and current lifecycle Stage declarations.
- Known edge endpoints, unique pairs, nonempty reasons, reason endpoint/owner
  agreement and consistency of edges with successor adjacency.
- Multiplicity agreement between recorded index references and graph reasons plus
  Stage assignments, including root source agreement.

Obvious incompatibilities raise `StageOrderInputError`, stable code
`invalid_stage_order_input`, with a reason and owner when available. Checks fail
fast, visiting canonical vertices then supplied assignments/edges/references;
there is no canonical error-selection guarantee for arbitrary corrupted inputs.
Wrong top-level argument types raise TypeError. These guards are not a second
schema compiler or a general validation framework.

Callers must treat compiler inputs as snapshots and resolve/build again after
edits. M2.2 intentionally stores no Stage-order snapshot. Consequently, a valid
integer order changed before analysis is indistinguishable from the supplied
current order; there is no historical value to compare against. Invalid order
types and identity/assignment/source mismatches are detectable and rejected.
This API snapshots the current validated orders; it cannot certify historical
freshness or detect unrelated same-identity model edits. No hashes, state or new
IR snapshots are added to solve that separate problem.

## Conflict detection and deterministic witness selection

First obtain the lexicographically smallest dependency-only topological traversal
with a min-heap Kahn pass over the existing graph. This is private analysis, not a
returned order subsequently sorted by Stage. Completion of this pass precedes any
Stage-conflict reporting. Dependency cycles belong to M2.2: normal composition
fails in `build_dependency_graph` with `DependencyCycleError` before reaching this
API. A manually assembled cyclic graph violates the precondition and receives an
input error directing the caller to M2.2; it is never called a Stage conflict.

Traverse that dependency-only order, propagating one highest-ranked assigned
ancestor per vertex, through assigned **and unassigned** vertices. At an assigned
vertex, a higher-ranked ancestor proves a backwards dependency path. Report the
first such destination in this canonical traversal. Among candidate ancestors,
prefer greatest numeric order, then smallest case-sensitive owner identity. At
equal rank the current vertex also competes as an origin by owner identity. For
multiple paths from the same chosen origin, retain the first incoming predecessor
processed in the dependency-only traversal; sorted successor iteration completes
the tie policy. This is deterministic, not a shortest-path promise.

Store one parent per vertex, reconstructing only the selected path iteratively.
A descending assigned-to-assigned dependency path is precisely a contradiction
with strict ascending group precedence. Unassigned intermediates do not conceal
it. Explicit and implicit edges participate identically.

`StageOrderConflictError`, code `stage_order_conflict`, exposes a frozen/slotted
`diagnostic` with:

- `higher` and `lower`: both ranked assignments, including original paths.
- `witness`: actual directed dependency path from higher to lower owner.
- `edges`: every path edge, preserving all immutable M2.2 reasons and list indexes.
- `sources`: detached origins of every path vertex and both referenced Stage
  declarations, sorted by identity and separate from portable evidence.

For example, with workloads order 40 and network order 10:

```text
stage_order_conflict: dependency path VirtualMachine/app -> Network/base;
VirtualMachine/app assigned to Stage/workloads order=40 field=('lifecycle', 'stage');
Network/base assigned to Stage/network order=10 field=('lifecycle', 'stage');
VirtualMachine/app -> Network/base: explicit owner=Network/base field=('depends_on', 0);
... origins include filename, document number and document-root line/column ...
```

Only one deterministic contradiction is reported, with no successful partial
analysis. Edge objects may be shared with the already immutable graph; no mutable
resource or source-location object is shared.

## Final ordering algorithm and complexity

After conflict checking, a second Kahn pass tracks remaining members of each
populated numeric Stage group. The lowest unfinished group is active. A vertex is
eligible only when all real prerequisites are emitted and either it is unassigned
or its group is active. Dependency-ready vertices in later groups wait in private
buckets. Finishing a group releases the next group's dependency-ready members.
A single min-heap always selects the smallest currently eligible logical identity.
This allows unassigned vertices before, between or after groups, including
unassigned prerequisites needed to unblock the current group.

No synthetic vertices or cross-product Stage edges are created. Do not sort the
result afterward. Both passes and witness reconstruction are iterative. Working
storage is O(V + E + R), including compatibility counters for R original references;
after canonical checks/sorting, heap traversal costs O((V + E) log V) or less.
Stage-group bookkeeping and ancestor propagation are linear apart from sorting
distinct numeric orders. No quadratic number of precedence edges is materialized.

## M2.4 and deferred behavior

M2.4 can compose loading/resolution, classification, M2.2 graph building, then this
analyzer for a provider-free graph view. It should display declared edges and
Stage constraints distinctly and render structured errors safely. It must not
label this order an apply/delete schedule. That CLI is a separate increment.

This change leaves `diatonic validate`, normalized IR serialization, schemas,
reference resolution and M2.2 graph output unchanged. Provider/capability analysis,
phase readiness, runtime scheduling, deletion reversal, state, plan/apply and
execution remain deferred. No lifecycle defaults are introduced.
