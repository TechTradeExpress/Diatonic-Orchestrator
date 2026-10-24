# Milestone 2: Dependency analysis and offline provider resolution

**Progress:** M2.1–M2.8 are implemented. M2.9 adds the final planned offline CLI
view, `diatonic explain`, for independent review. The original M2.0 roadmap below
remains the incremental scope and acceptance baseline; ADR-0011–0017 document
implementation policies. No execution milestone is authorized by this completion.

The normative contract is [Resource Model v0.1](resource-model/v0alpha1.md).
[ADR-0009](decisions/0009-m2-dependency-lifecycle-boundaries.md) distinguishes its
requirements from proposed internal decisions and open questions. Review those
decisions before implementing the affected increment. Each numbered increment
below is a separate, focused Draft PR, not authorization to implement all of M2.

## Baseline and goal

M1 provides strict loading, five typed resource kinds, canonical identity/reference
resolution, network-scoped IPv4 checks, immutable normalized IR and `diatonic
validate`. Its resolver intentionally accepts cyclic links and records Stage
assignment alongside other references. Its IR is not a graph or operation plan.

M2 adds deterministic logical dependency/stage analysis and inspectable offline
capability-to-provider selection. It must work without contacting infrastructure,
installing drivers, loading executable plugins or running providers. Graph and
baseline explain must work with no Provider or ProviderBinding declarations.

Keep the M1 loader, resolver, IPv4 validation and normalized resource serialization
contracts stable. Add separate immutable analysis results, with provenance outside
portable data. Do not quietly add graph/provider requirements to the existing
`validate` command; any such behavior change needs its own explicit issue/review.

## PR-sized increments

### M2.1 — Classify declared dependencies and Stage assignments

**Goal:** turn already resolved links into explicit dependency facts, retaining why
each fact exists. **Dependencies:** M1.5–M1.8 and review of ADR-0009 §1.

**Acceptance:** classify `depends_on` as explicit prerequisites; VM placement,
interface networks and image as implicit prerequisites; Stage assignment as a
separate relation. Preserve owner identity, original field paths/list indexes and
document-root sources. Sort results independently of input path/order; retain all
origins when explicit/implicit declarations imply the same prerequisite. Cover
omissions, repeated interface links, same names across kinds, forward/cross-file
links, explicit dependencies on Stage resources and input immutability.

**Non-goals:** cycle/topological algorithms, phase/operation edges, provider links,
Stage rank defaults, changes to `ResourceIndex.references` or M1 IR exports.

### M2.2 — Build the logical graph and diagnose cycles

**Goal:** construct an immutable provider-free graph of resource identities and
deduplicated prerequisite-to-dependent edges. **Dependencies:** M2.1.

**Acceptance:** include isolated resources; preserve edge-origin evidence separately;
produce sorted vertices, successors and reason records. Detect self-cycles and
longer cycles with a deterministic closed witness path and all relevant resource,
field-path and root-source context. Test empty/disconnected graphs, duplicate
edges, multiple possible cycles and permuted file/mapping order. Fail without
returning a successful partial graph analysis when a cycle exists.

**Non-goals:** Stage precedence, operation scheduling, phase nodes, provider demand,
implicit inference beyond the M2.1 classification, reversing edges for deletion.

### M2.3 — Apply Stage constraints and deterministic topological ordering

**Goal:** combine an acyclic dependency graph with reviewed Stage precedence.
**Dependencies:** M2.2 and approval of ADR-0009 §2's partial-stage policy.

**Acceptance:** lower declared Stage orders precede higher ones; same/equal-order
stages add no mutual precedence. Unassigned resources remain unassigned. Return
the lexicographically smallest eligible identity at each topological step, subject
to both dependency and Stage constraints. Reject a direct late-to-early dependency
and an indirect contradiction passing through an unassigned resource. Explain the
dependency chain and Stage assignments/orders causing each conflict. Test negative
and zero Stage orders, ties, unused stages, absent assignments, stage-independent
cycles and equivalent inputs in different layouts. Derived Stage constraints stay
distinct from declared dependency edges and do not modify resource data.

**Non-goals:** runtime barriers, parallel execution, phase readiness, a default
stage, forcing unassigned resources into an arbitrary rank, silently overriding
either dependency requirements or Stage order.

### M2.4 — Expose provider-free `diatonic graph`

**Goal:** a thin CLI over M1 compilation and M2 logical graph/Stage analysis.
**Dependencies:** M2.3.

**Acceptance:** accept explicit YAML paths; show deterministic identities, edges
and their explicit/implicit reasons, with Stage assignments identified separately.
Report cycle/Stage conflicts using safe literal diagnostics and document-root
positions. Define exact command syntax/output in that PR. Test missing inputs,
invalid M1 data, cycles, Stage conflicts, stable output and no files written.
No Provider/Binding, capability catalogue or installed driver is needed.

**Non-goals:** executing a workflow, showing an apply/delete schedule, provider
selection, filesystem discovery, introducing a graph serialization protocol.

### M2.5 — Add the portable Provider instance schema

**Goal:** model the §12.2 Provider envelope, `spec.driver` and opaque configuration.
**Dependencies:** M2.4 as the proposed delivery sequence, not a schema dependency.

**Acceptance:** strict kind/API/envelope/identity/dispatch tests; distinguish driver
ID from Provider identity. Preserve JSON-compatible configuration and platform
extension boundaries without vendor fields in portable infrastructure specs.
Document requiredness using the contract's demonstrated shape; keep configuration
validation separate from driver discovery. Numeric/string coercion and extra
schema keys fail. References to secrets remain references; do not add credentials
or real endpoints to examples, and do not claim to validate arbitrary vendor
credential contents inside opaque configuration.

**Non-goals:** driver import/discovery, configuration interpolation, secret lookup,
provider process/manifest protocol, connectivity or executing even a mock driver.

### M2.6 — Add ProviderBinding schema and declaration validation

**Goal:** model §12.3 capability, selector, Provider reference and priority fields.
**Dependencies:** M2.5 and review of ADR-0009 §5's selector/priority policy.

**Acceptance:** strict schema/dispatch tests and exact `Provider/name` references;
a separate M2 validator checks referenced Provider existence/kind against the index.
Keep M1.5's resolver algorithm and recorded links unchanged. Exact kind/label
selectors, explicit priority requiredness and rejection of unsupported selector
syntax must be documented as implementation choices. Include missing/wrong-kind
Provider targets, empty/invalid values, strict priorities and source diagnostics.

**Non-goals:** selecting a provider, label expression languages, implicit driver
defaults, treating binding configuration links as infrastructure dependencies.

### M2.7 — Define offline capabilities and explicit phase requests

**Goal:** a small, inspectable vocabulary mapping supported resource/phase pairs to
capabilities, with supplied driver support metadata. **Dependencies:** M2.6 and
review of ADR-0009 §§3 and 5.

**Acceptance:** model an explicit analysis request for a resource phase; preserve
managed/external/disabled/unspecified distinctions. No request is inferred merely
because a resource exists or `desired_state` is absent/present. Test known mappings
(e.g. VM provision to `virtual_machine.provision`), unknown pairs, absent ownership,
and external/disabled requests producing no managed-provider demand. Use plain
in-memory descriptor fixtures; missing capability/driver metadata is explicit,
never guessed from a driver name. Do not invent Image/Stage capability names.

**Non-goals:** deciding actual operations, implicit lifecycle defaults, applying
provider protocols, importing executable plugins, platform-specific core branches.

### M2.8 — Resolve required managed capabilities deterministically

**Goal:** offline binding selection for an explicit required managed-phase request.
**Dependencies:** M2.7.

**Acceptance:** filter by capability, reviewed selector semantics and declared
compatibility metadata; explain considered/rejected bindings. Resolve exactly one
winner according to reviewed explicit priority rules; diagnose zero matches,
missing/unsupported capability metadata and tied winners deterministically.
Never choose by declaration/file order. Include permutations, nonmatching/missing
labels, unknown drivers, incompatible support, ties and source origins. External,
disabled and unspecified ownership must not become managed actions or guessed
provider requests. Return immutable decision records, not initialized drivers.

**Non-goals:** backend availability/authentication, live negotiation, outputs,
provider execution, phase sequencing or deciding whether deletion is necessary.

### M2.9 — Expose provider-free `diatonic explain`

**Goal:** explain a resource's dependencies, Stage assignment and declared lifecycle;
optionally report an explicitly requested offline binding analysis.
**Dependencies:** M2.4 and M2.8.

**Acceptance:** baseline explain succeeds without any Provider/Binding declarations
or driver metadata and clearly says when provider resolution was not requested.
An explicit phase query reports external/disabled/unspecified without ownership
defaults; required managed queries report selection or deterministic failure.
Freeze command syntax in that PR, using explicit files and a canonical resource
identity. Test unknown identities, graph conflicts, omission preservation,
phase-query failures, literal diagnostic text, stable output and no writes.

**Non-goals:** promising actual readiness, evaluating secrets, reading live state,
rendering an execution plan, silently demanding providers for all managed phases.

## Completion and later milestones

M2 is complete when the reviewed graph/Stage analysis and offline provider
selection APIs and both CLI views have focused tests, with all M1 regressions
passing. It does not mean the whole MVP or every runtime safety rule is complete.

Mock provider execution, transport/protocol implementation and destructive-operation
safety checkpoints belong to M3+ with explicit operation-context designs. Real
adapters start at M4+. State ownership, a journal, secret resolution, plan/apply,
deletion/adoption semantics and lifecycle policy engines are separate later work.
Do not implement them as prerequisites for an offline M2 inspection command.
