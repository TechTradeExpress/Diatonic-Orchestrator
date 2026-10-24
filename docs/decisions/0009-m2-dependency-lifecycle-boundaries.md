# ADR-0009: M2 dependency, Stage and lifecycle boundaries

- **Status:** Proposed for independent review; documentation only.
- **Baseline:** M1.8 merged in PR #17; no graph or provider implementation exists.
- **Scope:** proposed internal analysis semantics for [M2](../milestone-2.md).
- **Authority:** [Resource Model v0.1](../resource-model/v0alpha1.md) is unchanged.

In each section, **Contract** identifies requirements explicitly stated by the
Resource Model; **Proposal** is an M2 design choice requiring review; **Deferred**
identifies questions not decided by this PR. These categories must not be treated
as interchangeable. The proposals are not new `iac/v0alpha1` YAML requirements or
changes to `iac-provider/v0alpha1`.

## 1. Resolved links, dependency facts and graph edges

**Contract (§§6, 8–9, 16, 23):** identity is case-sensitive `Kind/name`, independent
of files. Explicit dependencies use `depends_on`. References such as VM placement
and network attachments imply prerequisites; a Stage assignment identifies a broad
layer and is not a replacement for the DAG. The compiler must detect cycles and
report a readable dependency path before eventual execution.

**Current implementation:** `ResourceIndex.references` includes explicit links,
Stage assignments and VM spec links, retaining repeated targets and field paths.
The M1.5 resolver deliberately accepts self/cyclic links. M1.6 snapshots all those
links without graph semantics. M1.8 checks IPv4 data and does not change that fact.

**Proposal:** derive a separate immutable dependency analysis, without changing
the resolver, its reference records or normalized portable resource data:

| Resolved link | Classification | Dependency graph effect |
| --- | --- | --- |
| `depends_on[i]` | Explicit prerequisite | Target → owner |
| VM `spec.placement.target` | Implicit prerequisite | Hypervisor → VM |
| VM `spec.interfaces[i].network` | Implicit prerequisite | Network → VM |
| VM `spec.image.ref` | Implicit prerequisite | Image → VM |
| `lifecycle.stage` | Stage assignment | Separate rank constraint; no assignment edge |

Every supported logical resource identity is a vertex, including isolated
declarations and meta resources. A vertex does not imply a runnable action.
An explicitly declared `depends_on: [Stage/x]` remains an explicit dependency;
it is different from merely assigning `lifecycle.stage: x`. Future binding-to-
Provider configuration references are a separate validation relation, not automatic
infrastructure edges. Unclassified future reference fields must be handled by an
explicit reviewed classification, never silently assumed to be prerequisites.

Use edge direction **prerequisite → dependent** consistently in diagnostics and
CLI views. For `A depends_on B`, store `B → A`; do not expose a mixture of forward
edges and predecessor maps without labeling them. Deduplicate by ordered endpoint
pair for graph traversal, while retaining every origin: explicit/implicit reason,
original owner ID, field path (including integer indexes) and root source. A VM's
two interfaces on one Network plus an explicit dependency produce one graph edge
with three reasons. Do not deduplicate M1's reference list or rewrite user YAML.

Sort vertex and endpoint identities lexicographically with exact case. Sort edge
reasons by explicit-before-implicit, owner identity and field path, comparing list
indexes numerically; provenance paths must not determine graph order. Sources stay
separate, and coordinates remain document-root positions. Analysis must detach
mutable inputs or consume immutable snapshots; do not reintroduce M1.5's mutable
model exposure into graph results.

**Proposal for cycle witnesses:** inspect roots and successors in sorted identity
order; report the first closed cycle found by that deterministic traversal, rotated
to start at its smallest identity without reversing edge direction. Include the
origin reasons for each edge, including both endpoints' sources when useful.
Self-edges are cycles. Suggested internal code `dependency_cycle` is provisional,
not an already implemented error. Report one deterministic failure and no successful
partial ordering; enumerating all cycles is unnecessary.

Illustrative declarations (pseudocode; each ID denotes an existing resource):

```text
VirtualMachine/a depends_on VirtualMachine/c
VirtualMachine/b depends_on VirtualMachine/a
VirtualMachine/c depends_on VirtualMachine/b

edges: c → a, a → b, b → c
witness: VirtualMachine/a → VirtualMachine/b → VirtualMachine/c → VirtualMachine/a
self-cycle: VirtualMachine/a depends_on VirtualMachine/a ⇒ a → a
```

**Deferred:** phase-level readiness, outputs and reverse teardown order require
operation context. This resource graph does not mean every phase of a prerequisite
must execute before every phase of its dependent, and is not an apply/delete plan.

## 2. Stage assignments and topological ordering

**Contract (§§8–9):** Stage has an integer `spec.order`; resources assign a Stage
through a bare lifecycle name. Stage order and resource dependencies must both be
respected. The document does not define ties, unassigned resources or conflict
precedence. Existing schemas permit zero/negative orders and omitted assignments.

**Proposal:** treat lower numeric order as earlier. For assigned resources, every
lower-order group precedes higher-order groups; same Stage or equal numeric order
adds no ordering between members. Equal orders need not have the same Stage name.
Stage identity names are not a secondary rank. Explicit dependencies inside an
equal-order group still apply.

Keep these constraints separate from dependency edges and from M1 reference data.
Conceptually combine dependency precedence with lower-group-before-higher-group
precedence for cycle/ordering analysis. An implementation may use internal barriers
to avoid materializing all cross-group pairs; such synthetic nodes are not public
resource identities and must not leak into portable output or dependency reasons.

Unassigned resources have **no inferred rank**: do not inherit a prerequisite's
Stage, assign order zero, or require a Stage just to display a graph. They may be
placed anywhere consistent with dependencies and the declared Stage constraints.
A Stage declaration's `spec.order` defines the rank of its assigned members; it
does not assign that Stage vertex to itself. Meta vertices, like any others, gain
a rank only from an explicit lifecycle Stage assignment.

Check dependency cycles first. If the dependency graph is acyclic but combined
Stage/dependency precedence is cyclic, report a Stage-order conflict (proposed
code `stage_order_conflict`). Never silently ignore a dependency, move an assigned
resource to a new Stage, or prefer Stage order over the prerequisite. Include
the dependency chain and the two Stage IDs/orders and assignment fields/sources
that make it impossible. Choose the first contradiction in canonical traversal
order; implementation must test its witness choice under input permutations.

For an acyclic combined relation, choose the lexicographically smallest currently
eligible identity at each topological step. Do not simply sort a completed
dependency order by Stage rank, which can break prerequisites. Empty inputs yield
an empty order. This is a deterministic analysis order, not runtime scheduling.

Potential conflict (fragments, with referenced declarations supplied):

```yaml
# Stage/network has order 10; Stage/workloads has order 40.
kind: Network
metadata: {name: base}
lifecycle: {stage: network}
depends_on: [VirtualMachine/app]
```

`VirtualMachine/app` assigned to workloads must precede `Network/base` due to
the explicit dependency, while the Stage constraint requires the reverse.
An indirect path `app → unassigned-helper → base` is the same contradiction;
testing only edges whose endpoints both have stages would miss it. If both stages
had order 10, that Stage conflict would disappear, though any dependency cycle
would remain invalid.

**Deferred/review gate:** strict group precedence with unassigned resources is a
proposal, not fully specified public semantics. Review it before M2.3. Whether
runtime completion barriers operate per phase or per resource, and whether future
policy requires stages on actionable resources, are later operation/policy questions.

## 3. Lifecycle ownership and required phase requests

**Contract (§§10–11):** phases are `observe`, `provision`, `configure`; ownership
is `managed`, `external`, `disabled`. Managed means the orchestrator must resolve
and execute a compatible provider when that phase is required; external ownership
is outside the tool, and disabled means not applicable. Missing compatibility must
fail before execution. The document defines no defaults for omitted lifecycle
values. ADR-0002 and the current models preserve those values as unspecified.

**Proposal for offline M2 analysis:** require an explicit resource/phase analysis
request before deriving provider demand. A YAML `managed` value alone does not
request every possible operation, and `present`/`absent` alone does not select a
phase. Generic graph and baseline explain require no providers. For an explicitly
requested phase:

| Declared ownership | M2 analysis outcome |
| --- | --- |
| `managed` | Resolve the required capability; fail on unavailable/ambiguous support |
| `external` | Report externally owned; no managed-provider demand or action |
| `disabled` | Report not applicable; no managed-provider demand or action |
| omitted / unspecified | Report unspecified; do not invent ownership or select a provider |

M2 never executes any of these outcomes. An eventual execution request cannot
silently proceed with unknown required ownership; later operation design must
decide how to reject or require explicit policy. Declaring a dependency on an
external resource does not transfer its ownership or automatically provision it.

Example supported by the current envelope:

```yaml
api_version: iac/v0alpha1
kind: Hypervisor
metadata: {name: host01}
spec:
  management: {address: 192.0.2.10}
lifecycle:
  stage: platform
  desired_state: present
  phases: {observe: managed, provision: external, configure: external}
  prevent_destroy: true
```

This physical host may require an observe provider for an explicit observe query;
external provision/configure must never turn into creating or configuring the host.
`Stage/platform` must be separately declared, as in the current Stage fixture.

**Deferred:** deciding which phases a real operation needs, readiness of external
prerequisites, observed state, phase sequencing and unsupported ownership-policy
combinations. No lifecycle policy engine or defaults are introduced in M2.0.

## 4. Desired state and prevent_destroy are different from operations

**Contract (§10 and §23):** desired state is `present` or `absent`; destructive
behavior must respect `prevent_destroy`. The contract does not say every absent
declaration immediately causes deletion, nor define removal-from-YAML behavior.

**Proposal:** `present` expresses desired existence and `absent` expresses desired
nonexistence. Neither proves an actual create/update/delete operation without
observed state, phase ownership and a later operation plan. Already absent may
mean no change; present might still entail a destructive replacement. Resource
omission from a configuration must not be treated as an implicit delete request.

```yaml
api_version: iac/v0alpha1
kind: VirtualMachine
metadata: {name: retired}
spec:
  cpu: {cores: 1}
  memory: {mib: 512}
lifecycle:
  desired_state: absent
  phases: {provision: managed}
  prevent_destroy: true
```

The combination is a valid static declaration with intent and a safety guard.
Do not blanket-reject it during schema parsing. It may yield a no-op if the VM is
already absent. If a later plan proposes destroy/replacement, the guard must block
that destructive step: it cannot appear as approved/executable. A diagnostic plan
may show a blocked action, but must make the block explicit. Recheck the guard at
the final execution boundary against the applicable validated configuration.
No provider request, operation or deletion is inferred by this example today.

**Later checkpoints (M3+, proposals requiring their own review):** operation
classification with explicit destructive effects; pre-plan-approval rejection or
blocked status; execution-time enforcement before dispatch; and freshness checks
when state/configuration changes. A backend adapter must not bypass those guards.
`prevent_destroy: false` or omission is not blanket authorization to delete.

**Deferred:** absence versus external ownership, replacement/disk destruction,
adoption/import, configuration removal, override authorization and backend-specific
safety guarantees. These need explicit planning/execution design and tests; M2
adds no delete behavior, state engine, plan/apply or lifecycle policy evaluator.

## 5. Provider concepts and deterministic selection

**Contract (§§11–13, 29, 31):** keep these distinct:

| Concept | Meaning |
| --- | --- |
| Driver | Implementation identifier; not a logical infrastructure resource kind |
| Provider | Named instance configuring a driver for an environment |
| ProviderBinding | Selector/capability/priority declaration referring to a Provider |
| Capability | Supported operation such as `virtual_machine.provision` |
| Lifecycle phase | Resource intent/ownership context such as `provision` |

Providers advertise capabilities. A required managed phase with no compatible
provider is an error. Equal effective-priority ambiguity must not be resolved by
arbitrary selection. Core cannot branch on platform/engine names; extensions remain
under `extensions.<platform>`. Execution guarantees may differ across backends.

**Proposal:** Provider/Binding schema PRs extend typed dispatch but keep M1.5's
resolver algorithm unchanged. Validate binding `spec.provider` existence/kind in a
separate M2 declaration step; do not reinterpret it as an infrastructure edge or
silently add it to M1.5's recorded link categories.

Use supplied, immutable in-memory driver descriptors for offline capability
support analysis. They contain explicit driver IDs/support data, not executable
objects, live connections or a new Provider YAML field. No driver installation,
process protocol, imports, secret resolution or network discovery is necessary.
If support/compatibility metadata is unavailable, report that uncertainty as an
explicit analysis failure for a required request; do not infer it from a driver
name, platform extension or the existence of a matching binding. A driver ID being
known does not prove live availability or authentication.

Map only explicitly supported resource/phase pairs to capabilities. VM provision
maps to `virtual_machine.provision` (§11). Image or meta-resource capability names
are not specified and must not be invented by string conversion. Distinguish an
unsupported request from a valid capability with no matching provider.

Initial selection policy proposed for review:

1. Consider bindings for the requested capability with exact matching kind and
   conjunction of exact label matches. Missing labels do not match. No expressions
   or hidden selector-specificity score; complex expressions remain open in §33.
2. Verify the referenced Provider and supplied driver capability/compatibility
   metadata. A binding's capability string alone is not proof of support.
3. Among compatible matches, highest numeric priority wins. Require an explicitly
   declared strict priority initially rather than inventing an omission default.
4. Zero compatible candidates fails deterministically. Multiple highest-priority
   bindings fail as ambiguous, listing all candidate origins in sorted binding
   identity order. Do not choose the first file or retry lower priority after an
   ambiguous result. As a conservative proposal, equal winning bindings to the
   same Provider also remain ambiguous until a deduplication rule is reviewed.

Priority direction, requiredness, same-Provider ties and the shape of compatibility
metadata are **proposals/open review points**, not requirements already fixed by
the public document. Schema/resolution PRs must settle them explicitly. Driver
support metadata may describe compatibility without hard-coded vendor branches;
this ADR does not specify a general extension-schema registry.

**Deferred:** live driver discovery, protocol negotiation, configuration/credential
validation, cross-provider outputs, runtime health, per-platform feature guarantees
and driver replacement. M2 can explain a static selection but cannot promise an
operation will succeed on infrastructure.

## 6. Worked VM dependency example and review gates

This excerpt uses current VM field names and supported kinds. Supporting Network,
Hypervisor and Image declarations are in `examples/infrastructure/resources.yml`;
Stages are in `tests/fixtures/reference-stages.yml`. A separate minimal
`VirtualMachine/bootstrap` declaration is assumed for the explicit prerequisite.
This is an explanatory fragment, not a standalone complete input stream.

```yaml
api_version: iac/v0alpha1
kind: VirtualMachine
metadata: {name: app01}
spec:
  cpu: {cores: 4}
  memory: {mib: 4096}
  placement: {target: Hypervisor/host01}
  interfaces:
    - name: primary
      network: Network/servers
      ipv4: {mode: static, address: 192.0.2.20/24}
  image: {ref: Image/debian13}
depends_on: [VirtualMachine/bootstrap]
lifecycle: {stage: workloads}
```

Proposed edges are bootstrap → app01 (explicit), host01 → app01, servers → app01
and debian13 → app01 (implicit). The Stage/workloads link is an assignment, not a
fifth dependency edge. Explicitly repeating Network/servers in depends_on would
add a reason to its existing graph edge, not a second traversal edge. None of this
selects a lifecycle phase or a provider.

Review these questions before the corresponding implementation increments:

1. Approve logical resource vertices, prerequisite → dependent direction, origin
   retention and the separate Stage-assignment relation (M2.1–M2.2).
2. Approve strict ordered-stage groups, equal-order behavior and unassigned-node
   handling, especially indirect contradictions (M2.3).
3. Confirm explicit offline phase requests and how unsupported/unspecified requests
   are presented without introducing ownership defaults (M2.7/M2.9).
4. Settle priority direction/requiredness, same-Provider ties, selector subset and
   supplied driver compatibility metadata before M2 provider schemas/resolution.
5. Keep destructive-effect classification and prevent_destroy enforcement attached
   to future operation plans/execution, not inferred from static desired state.

Existing tests anchor the separation: `test_self_and_cyclic_links_resolve_without_graph_semantics`
keeps M1.5 resolution independent; omission/null and deep-snapshot tests in
`test_normalized_ir.py` preserve declaration semantics; IPv4 tests in
`test_ipv4_semantics.py` preserve network-scoped validation without topology or
lifecycle inference. Add M2 graph/selection tests alongside these contracts rather
than rewriting those tests to make unrelated layers acquire new responsibilities.
