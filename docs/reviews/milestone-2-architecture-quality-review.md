# M1/M2 architecture and quality audit

- **Audited main:** `769d710b59f12c55b50389883a18b7b1010b088f`.
- **Audit date:** 2026-10-25 (UTC).
- **Scope:** integrated M1/M2 implementation and its readiness boundary with M3.
- **Tracking:** [Issue #38](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/38).
- **Change:** this report only; recommendations are not implemented or approved here.

## 1. Executive summary and verdict

**CONDITIONAL GO for a separately authorized, synthetic-only M3 implementation;
NO-GO for launching a provider now or implementing a real credential-bearing
adapter against the current offline guarantees.** Continued design work may
proceed. The conditions in section 11 must be accepted and satisfied before the
affected runnable implementation is merged or a child is launched. This verdict
is not an execution permit.

The implemented compiler is a coherent offline system. Local Ruff passes and
**1,424 tests pass**. Additional independent bounded oracles found no mismatch in
400 Stage-order cases and 400 Provider-resolution cases. This is useful evidence,
not proof of complete correctness. No P0 defect was demonstrated. Two P1 gates,
four P2 improvements and four Notes are recorded below.

The strongest reusable properties are strict parsing/schema boundaries,
canonical identities, reference origins, detached immutable analysis snapshots,
deterministic graph/Stage algorithms, and conservative three-valued driver
support handling. Logical ordering and offline selection do not authorize
operations. Provider configuration remains opaque and full-fidelity IR exports
remain unredacted. Current CLI omission of that configuration is narrower than a
confidentiality guarantee. A separate confirmed gap is raw terminal-control
characters in names surviving literal Rich rendering.

[ADR-0018](../decisions/0018-provider-configuration-secret-boundary.md),
[ADR-0019](../decisions/0019-m3-operation-context.md) and
[ADR-0020](../decisions/0020-m3-provider-protocol-error-isolation.md) are merged
**Proposed** designs. No secret backend, operation authorization, dispatch permit,
protocol gateway or provider executable exists. Their mechanisms cannot be used
as evidence of implemented protection.

## 2. Methodology, authority and limitations

The review used the normative [Resource Model](../resource-model/v0alpha1.md),
[Milestone 1](../milestone-1.md), [Milestone 2](../milestone-2.md), AGENTS,
contribution guidance, README, ADR-0001–0020, source/model/compiler/CLI modules,
test modules, fixtures, examples, project metadata and Actions workflow. Source
inspection was supplemented by an AST catalogue of every test function and
implementation entry point, regression execution, targeted real-pipeline probes,
and independent small-case algorithm oracles. Acceptance is not inferred from
passing test count alone.

Requirement precedence is: normative Resource Model; reviewed incremental ADR
policy where the model leaves a decision open; actual implementation; then future
proposal. A merged ADR is not automatically evidence of implemented runtime
behavior. M1/M2 issue/PR history and current GitHub rules/CI were queried rather
than inferred from README or older audits.

This is a fresh evidence pass by an agent that participated in earlier repository
work, not an assertion of independent organizational authorship. Independent
ChatGPT review and human disposition remain necessary. The audit does not prove
absence of all defects, exhaust arbitrary graphs/configurations, perform a
vulnerability database scan, test other OS/Python versions, or inspect unavailable
future runtime code. No real credentials, private endpoints or infrastructure
operations were used. Source positions below are document roots unless a loader
parser problem mark is explicitly available. Full object equality may include
provenance; portable equivalence deliberately excludes paths.

## 3. Contract and acceptance matrix

Statuses mean **Implemented and tested**, **Partially implemented**,
**Intentionally deferred**, **Unverified**, or **Contradiction**. No current
Contradiction is asserted solely because a broader future contract is not yet
implemented. Links identify concrete symbols/tests; the limits column bounds each
claim.

| Requirement/source | Implementation evidence | Test evidence | Status | Limits |
| --- | --- | --- | --- | --- |
| Envelope, namespaces, canonical identity; model §§5–8, M1.1 | [ResourceBase](../../src/diatonic/model/base.py#L20), [types](../../src/diatonic/model/types.py#L9) | [envelope](../../tests/test_resource_envelope.py#L20) | Implemented and tested | Generic envelope is not concrete-kind dispatch; names are case-sensitive. |
| Strict extra/type/finite-value checks; ADR-0002 | [StrictModel](../../src/diatonic/model/lifecycle.py#L13) | [invalid types](../../tests/test_resource_envelope.py#L127), [Provider JSON](../../tests/test_provider_model.py#L235) | Implemented and tested | No semantic vendor configuration validation. |
| Stage and minimal VM; M1.2 | [Stage](../../src/diatonic/model/stage.py#L15), [VM](../../src/diatonic/model/virtual_machine.py#L75) | [typed models](../../tests/test_typed_resources.py#L23) | Implemented and tested | Strict signed Stage order; positive CPU/memory; no ownership defaults. |
| Safe multi-document UTF-8 YAML; M1.3/ADR-0004 | [load_yaml_file](../../src/diatonic/compiler/loader.py#L116) | [documents](../../tests/test_yaml_loader.py#L24), [decoding](../../tests/test_yaml_loader.py#L215) | Implemented and tested | Explicit path order; no filesystem discovery or semantic parsing here. |
| Duplicate/nested/invalid keys, unsafe tags; ADR-0004 | [_StrictSafeLoader](../../src/diatonic/compiler/loader.py#L56), [_check_mapping_keys](../../src/diatonic/compiler/loader.py#L81) | [duplicates](../../tests/test_yaml_loader.py#L76), [keys](../../tests/test_yaml_loader.py#L92), [tags](../../tests/test_yaml_loader.py#L131) | Implemented and tested | YAML 1.1 scalar resolution retained; not a general configuration dialect. |
| Anchors/merge/alias and bounded failure policy; ADR-0004 | [loader](../../src/diatonic/compiler/loader.py#L56) | [merge/aliases](../../tests/test_yaml_loader.py#L157), [nesting](../../tests/test_yaml_loader.py#L268) | Implemented and tested | Aliases/merges rejected; unused anchors allowed. No file-byte/document-count ceiling. |
| Network/Hypervisor/Image/extended VM; M1.4/ADR-0005 | [Network](../../src/diatonic/model/network.py#L26), [Hypervisor](../../src/diatonic/model/hypervisor.py#L22), [Image](../../src/diatonic/model/image.py#L28), [VM spec](../../src/diatonic/model/virtual_machine.py#L64) | [infrastructure](../../tests/test_infrastructure_resources.py#L111), [syntax](../../tests/test_infrastructure_resources.py#L308) | Implemented and tested | Documented narrow requiredness and static-only interface mode; no provider-specific portable fields. |
| Full model §17 resource catalogue, including Project | [parse_resource](../../src/diatonic/model/resource.py#L22) | [unsupported kinds](../../tests/test_typed_resources.py#L106) | Partially implemented | Seven typed kinds; Project absent. M1/M2 incremental scope did not specify its schema (007). |
| Identity indexing, duplicates, forward/cross-file links; M1.5/ADR-0006 | [resolve_resources](../../src/diatonic/compiler/references.py#L124) | [forward links](../../tests/test_resource_references.py#L133), [both origins](../../tests/test_resource_references.py#L195) | Implemented and tested | Fail-fast document/reference order is intentional, not filename-independent error selection. |
| Typed references and Stage names; model §9 | [_declared_references](../../src/diatonic/compiler/references.py#L110), [reference types](../../src/diatonic/model/types.py#L15) | [missing links](../../tests/test_resource_references.py#L257), [wrong kind](../../tests/test_resource_references.py#L296) | Implemented and tested | Existence/kind only; no graph or execution semantics in resolver. |
| Network gateway, VM membership, duplicate host, gateway collision; M1.8/ADR-0008 | [validate_ipv4_semantics](../../src/diatonic/compiler/semantics.py#L59) | [IPv4](../../tests/test_ipv4_semantics.py#L100), [duplicates](../../tests/test_ipv4_semantics.py#L169) | Implemented and tested | Logical-network scope, host-address comparisons; no equal-prefix, broadcast, IPAM or topology policy. |
| Omission/null/default fidelity; M1.6/ADR-0007 | [normalize_resources](../../src/diatonic/compiler/normalize.py#L112), [lifecycle](../../src/diatonic/model/lifecycle.py#L27) | [omission/null](../../tests/test_normalized_ir.py#L151), [phase origins](../../tests/test_capabilities.py#L172) | Implemented and tested | `exclude_unset=True`; explicitly declared null/false/empty/zero retained. |
| Deterministic full-fidelity IR, provenance separation | [NormalizedIR](../../src/diatonic/compiler/normalize.py#L84) | [layout](../../tests/test_normalized_ir.py#L92), [exports](../../tests/test_normalized_ir.py#L271) | Implemented and tested | JSON keys canonical, meaningful lists retained; full configuration, not redacted output (001). |
| Immutable downstream snapshots; ADR-0007/0010–0016 | [NormalizedResource](../../src/diatonic/compiler/normalize.py#L42), [facts](../../src/diatonic/compiler/dependencies.py#L43) | [mutation isolation](../../tests/test_normalized_ir.py#L247), [graph maps](../../tests/test_dependency_graph.py#L300) | Implemented and tested | ResourceIndex itself retains mutable models; valid unmodified-input precondition remains (008). |
| Explicit/implicit facts and separate Stage assignments; M2.1 | [classify_dependencies](../../src/diatonic/compiler/dependencies.py#L108) | [origins](../../tests/test_dependency_classification.py#L136), [unknown fields](../../tests/test_dependency_classification.py#L361) | Implemented and tested | Every reference origin preserved; unknown shapes controlled. |
| All vertices, edge dedup/all reasons, iterative deterministic cycles; M2.2 | [build_dependency_graph](../../src/diatonic/compiler/graph.py#L190), [_find_cycle](../../src/diatonic/compiler/graph.py#L156) | [cycles](../../tests/test_dependency_graph.py#L165), [long chain](../../tests/test_dependency_graph.py#L226) | Implemented and tested | Prerequisite → dependent; closed witness first sorted DFS cycle, rotated, never reversed. |
| Stage constraints/conflicts and lexicographic eligible order; M2.3 | [analyze_stage_order](../../src/diatonic/compiler/stages.py#L373) | [indirect conflicts](../../tests/test_stage_order.py#L181), [oracle](../../tests/test_stage_order.py#L422) | Implemented and tested | Equal ranks no added order; unassigned stay unassigned; offline policy, not scheduler. |
| Provider named driver instances/opaque JSON; M2.5/model §12.2 | [ProviderSpec](../../src/diatonic/model/provider.py#L12) | [same driver](../../tests/test_provider_model.py#L382), [config](../../tests/test_provider_model.py#L281) | Implemented and tested | Required explicit config; no driver lookup, credential classification or secret resolution. |
| ProviderBinding declarations/targets; M2.6/model §12.3 | [schema](../../src/diatonic/model/provider_binding.py#L22), [validate_provider_bindings](../../src/diatonic/compiler/provider_bindings.py#L122) | [targets](../../tests/test_provider_binding.py#L338), [graph boundary](../../tests/test_provider_binding.py#L416) | Implemented and tested | `spec.provider` is a configuration link, not a resolved infrastructure edge. |
| Exact kind/all-label matching and strict priorities; M2.8/ADR-0014/0016 | [_matching_reasons](../../src/diatonic/compiler/provider_resolution.py#L447), [selection](../../src/diatonic/compiler/provider_resolution.py#L578) | [matching](../../tests/test_provider_resolution.py#L161), [priorities](../../tests/test_provider_resolution.py#L219) | Implemented and tested | Literal selector character subset is narrower than metadata (010); no specificity score. |
| Explicit phase queries and four ownership outcomes; M2.7 | [analyze_phase_request](../../src/diatonic/compiler/capabilities.py#L252) | [vocabulary](../../tests/test_capabilities.py#L107), [nonmanaged](../../tests/test_capabilities.py#L146) | Implemented and tested | Seven mapped managed pairs only; unsupported managed pairs controlled; no automatic requests. |
| Supplied support metadata; M2.7 | [DriverSupportMetadata](../../src/diatonic/compiler/capabilities.py#L378), [assessment](../../src/diatonic/compiler/capabilities.py#L421) | [three states](../../tests/test_capabilities.py#L401), [duplicates](../../tests/test_capabilities.py#L500) | Implemented and tested | Support is a declaration, not installed/trusted/runtime-compatible proof. |
| Ambiguity and unknown-support precedence; M2.8 | [resolve_phase_provider](../../src/diatonic/compiler/provider_resolution.py#L578) | [same-Provider ties](../../tests/test_provider_resolution.py#L241), [unknown ranks](../../tests/test_provider_resolution.py#L315) | Implemented and tested | Unknown decisive metadata precedes ambiguity; lower unknown cannot outrank confirmed winner. |
| Thin validate/graph/explain, streams/codes/no partial success; M1.7/M2.4/M2.9 | [validate](../../src/diatonic/cli.py#L149), [graph](../../src/diatonic/cli.py#L269), [explain](../../src/diatonic/cli.py#L318) | [validate](../../tests/test_cli_validate.py#L59), [graph](../../tests/test_cli_graph.py#L123), [explain](../../tests/test_cli_explain.py#L173) | Implemented and tested | 0 success, 1 expected analysis error, 2 usage. Validate intentionally accepts cycles/Stage conflicts. |
| Explain support JSON and explicit-only selection; ADR-0017 | [CLI support adapter](../../src/diatonic/cli_support.py), [explain](../../src/diatonic/cli.py#L318) | [strict JSON](../../tests/test_cli_explain.py#L663), [nonmanaged](../../tests/test_cli_explain.py#L361) | Implemented and tested | CLI-only local JSON, not provider protocol; unread for nonmanaged queries. |
| Literal output/confidentiality boundary; model §21, ADR-0018 proposal | [Text rendering](../../src/diatonic/cli.py#L308), [explanation projection](../../src/diatonic/cli_explain.py) | [config omitted](../../tests/test_provider_model.py#L518), [brackets](../../tests/test_cli_explain.py#L878) | Partially implemented | Rich markup safe; not general redaction or terminal-control filtering (001, 005). |
| General model §23 pipeline and complete semantic validation | [three CLI pipelines](../../src/diatonic/cli.py), ADR-0006–0017 | [failure precedence](../../tests/test_cli_graph.py#L659), [explicit phase](../../tests/test_cli_explain.py#L439) | Partially implemented | Reviewed staged offline sequence, not all future checks or automatic Provider demand (009). |
| Runtime lifecycle/destruction/provider protocol/state; §§10–15, 21–23, 31–33 | ADR-0018–0020 proposals only | No runtime tests or executable exist | Intentionally deferred | Must not infer execution guarantees from offline success. |
| Python beyond 3.12 and other OS behavior | [project metadata](../../pyproject.toml), [CI](../../.github/workflows/ci.yml) | Current CI Ubuntu/Python 3.12 only | Unverified | Local 3.12.3, CI 3.12.15; no demonstrated failure elsewhere. |

## 4. Implementation architecture and correctness

The implemented pipeline is explicit and compositional:

```text
explicit YAML files -> strict loader -> typed resources / identity / references
 -> IPv4 semantics -> ProviderBinding target checks -> normalized snapshot check
validate stops here
 -> dependency facts -> cycle-checked graph -> Stage constraints / logical order
graph stops here
 -> selected resource explanation -> optional explicit phase request
 -> managed-only offline Provider resolution with optional supplied support JSON
```

Library callers compose these passes themselves; calling `normalize_resources`
does not implicitly invoke every semantic check. Normalization is retained as a
check in the CLI, not exported as a file. References may point forward/across
files; no implicit Stage fixtures are supplied. The infrastructure example alone
fails for its undeclared platform/workloads Stages; adding
[reference-stages.yml](../../tests/fixtures/reference-stages.yml) makes it valid.

### Compiler and graph behavior

SafeLoader-derived construction rejects unsafe tags, duplicate decoded mapping
keys at any depth, invalid keys and roots, empty documents, aliases and merges.
File/decoding/parser failures are controlled. Resource validation is separate.
No byte-count ceiling exists for arbitrary local input; controlled excessive
nesting is not a memory/CPU sandbox. Future hostile process output needs its own
bounded parser, not reuse of this loader as a protocol boundary.

Resolver diagnostics intentionally fail first in supplied document/reference
order. Graph/provider/Stage portable ordering is canonical instead. This difference
is documented and tested; it is not nondeterminism in successful portable output.
Both duplicate declaration origins survive. YAML data is deep-copied; downstream
snapshots detach again. Root positions are not fabricated field coordinates.

IPv4 checks compare the address host, not interface-prefix equality. Duplicate
hosts are scoped to an exact logical Network identity; separate Networks may
reuse addresses. Network/broadcast reservations and topology semantics are not
promised. Required allocation types and syntax checks remain separate from these
cross-resource checks.

Dependency facts retain repeated explicit declarations and multiple interfaces,
including numeric indexes above nine. Graph edges deduplicate only endpoint pairs
and preserve all reasons. Stage assignment alone creates no dependency edge;
explicit `depends_on: [Stage/name]` does. Iterative DFS follows sorted roots and
successors; witnesses follow real direction, rotate to the smallest member and
close, including self-cycles. All indexed resources, including isolated Providers,
are vertices.

Stage analysis first respects the dependency DAG, then enforces strict lower-rank
completion before higher-rank eligibility without materializing quadratic cross-
group edges. Indirect late-to-early conflicts through unassigned nodes are caught.
Equal Stage orders add no precedence. Stage declarations have no rank merely
because they declare `spec.order`. Unassigned eligible resources can interleave.
The result selects the smallest eligible identity at each step; it is not a
sorted-afterward dependency list or an execution schedule.

### Provider correctness

Provider identity and driver ID remain distinct; multiple named Providers may
share a driver. Binding target validation is a separate exact typed lookup, with
no same-name/different-kind or same-driver fallback. It creates no graph edge.
Capability analysis requires a `PhaseRequest`; desired state, prevent_destroy,
Stage and dependencies do not create one. External, disabled and unspecified
outcomes need no metadata or provider selection, even for unmapped kind/phase pairs.

The initial vocabulary is exactly VM observe/provision/configure, Network
observe/provision, Hypervisor observe/configure. Managed requests outside this
table fail. Support descriptors are detached declarations with duplicate/type
checks, not executable compatibility discovery.

Selection uses exact capability, case-sensitive kind and conjunction of labels.
Highest numeric priority among declared-supported candidates wins. Supported ties
remain ambiguous even for the same Provider. Unknown support at or above the best
known priority blocks confidence before an ambiguity is claimed. Unknown lower
priority remains visible but does not block a unique winner. No matching, all
unsupported, decisive unknown, and confirmed ties have distinct codes. Candidate
traces preserve canonical ordering, reasons, priorities and provenance, without
Provider config.

## 5. Security review

The present system does not import or initialize drivers, resolve secrets, invoke
subprocesses, contact infrastructure, allocate addresses or write execution state.
The positive scope is offline compilation and declaration analysis. It is not a
sandbox for hostile inputs or a guarantee that callers never misuse exported data.

`ProviderSpec.config` intentionally accepts arbitrary nested JSON-compatible
values, including credential-like literals and `secret_ref` objects. §21 prohibits
raw secrets normatively, but generic JSON validation cannot classify every such
value. IR preserves the complete config. `to_dict()` and `to_json()` must therefore
be treated as full-fidelity potentially sensitive exports, never inherently safe
telemetry. ADR-0018 describes a proposed execution-contract/redacted-projection
boundary; it does not implement it. Key-name heuristics cannot close this gap.

Current CLI projections omit config/extensions rather than universally redact
all resource text. Synthetic-marker checks found no config disclosure in successful
Provider-only validate/graph/explain output. Existing tests also cover failures and
config noninspection in resolution. This does not cover secrets improperly placed
in identifiers, labels, paths, parser text, Python representations or exception
chains. Raw terminal controls are independently confirmed in finding 005.

Future preflight must fail closed on missing/invalid admitted configuration
contracts, required secret references, backend availability and authorization.
Offline selection/support JSON cannot authorize execution. Proposed protocol
admission, safe output projection, time/size budgets and child cleanup remain
future work, not existing mitigations. No runtime race, timeout disclosure or
exactly-once bug can be demonstrated while no runtime exists.

## 6. Determinism and immutability review

Portable IR mapping keys are recursively canonical; resource identity order is
case-sensitive lexicographic; explicit nulls and declared false/zero/empty values
survive, omitted defaults do not appear, and meaningful list order is preserved.
Repeated exports return new mutable data detached from internal immutable
snapshots. Source paths/document indices/roots remain separate.

Facts, graph, Stage analyses, binding summaries, capability analyses and resolution
results use frozen records/tuples/owned read-only mappings, without retained mutable
Pydantic resources/configs. Mutating inputs after construction does not alter those
completed results. Integer field indexes are ordered numerically, not as strings.

`ResourceIndex` has a read-only outer mapping but mutable Pydantic instances.
Focused consistency guards detect identity, reference multiplicity, schema or
provenance inconsistencies in several consumers; they are not a complete historical
freshness proof. A valid same-type edit can be consumed as current data. Negative
CPU assigned after validation can be serialized by a new normalization pass.
This is an unsupported mutated-input scenario, not evidence that invalid YAML
passes resource validation. Existing immutable snapshots remain unchanged.
Future authorization must bind a detached validated context rather than reopen
this index; ADR-0019 proposes that boundary.

Additional scratch checks used real model/resolver/index objects:

- 400 deterministic Hypothesis small-DAG cases compared Stage analysis against an
  independently expanded strict-rank graph and min-heap Kahn oracle: **291 valid,
  109 conflicts, no mismatch**. Every returned conflict witness used real edges.
- 400 Provider cases compared the resolver with enumeration of every possible
  supported/unsupported completion of unavailable metadata: **100 selections,
  61 no-match, 44 unsupported, 164 uncertain, 31 ambiguous, no mismatch**.
- Reordered/renamed input documents preserved portable snapshots and graph/order
  facts. Driver-sharing cases preserved separate Provider identities.

These bounded probes complement the existing 75-example Stage Hypothesis test,
long-chain tests and large-candidate tests. They do not establish unbounded proofs.

## 7. CLI and developer experience

`validate` checks syntax, schemas, identity/references, IPv4 and binding targets;
it intentionally accepts cyclic dependencies and incompatible Stage orders.
`graph` adds cycle/Stage analysis. Baseline `explain` is provider-free; only an
explicit managed `--phase` attempts offline selection. Nonmanaged phase requests
do not read even an invalid supplied metadata path. A cycle elsewhere in supplied
resources fails explanation before success. No partial success is emitted.

Success is stdout/0; expected analysis errors stderr/1; Typer usage stderr/2.
Existing tests freeze byte-level old-command compatibility, terminal widths,
root help/version, bracket-containing identities/paths, source locations and
witness detail. Rich `Text` prevents markup interpretation but does not remove ESC
controls. Help ANSI handling previously fixed in PR #37 is a regression lesson,
not a current failure. ADR-0019's malformed closing delimiters were fixed before
PR #42 merged; they are not a current defect either.

README examples are backed by tests and intentionally use explicit Stage fixtures
and synthetic provider declarations. The M2 progress introduction and some older
docstrings/template wording lag completion (006). Explain does not dump full specs,
config, extensions or secret references. Logical topological position is described
as offline order, never authorization to apply or destroy.

## 8. Testing, tooling and governance

Local required checks pass on Python **3.12.3**. Exact audited main CI also passes
on Ubuntu/Python **3.12.15**: [run 40176630237](https://github.com/TechTradeExpress/Diatonic-Orchestrator/actions/runs/40176630237),
head `769d710b59f12c55b50389883a18b7b1010b088f`, `lint-and-test` successful,
Ruff passed, **1,424 passed in 12.91s**. This historical-main evidence is separate
from local **1,424 passed in 15.52s**, and from any later PR check.

The suite covers all current compiler layers, sources, mutation isolation,
controlled corrupted inputs, graph witnesses, Stage oracles, matching uncertainty,
CLI streams and no state writes. Quantity alone does not certify security, typing
or future runtime behavior. No coverage-percentage or mutation-testing claim is
made. Broad nested input/resource size limits and other Python/OS versions remain
outside the demonstrated test boundary.

Optional `mypy src/diatonic` fails with **29 errors in 13 files (28 checked)**:
four missing PyYAML-stub errors, seven concrete-spec/base-field overrides, and
18 other annotation/narrowing/constructor errors. This is not a CI-required check
or a demonstrated runtime failure, but weakens the advertised typed-library
maintenance baseline. No stubs/dependencies were added during the audit.

Dependencies use bounded major-version ranges without a tracked lock. `uv sync`
created an untracked lock during verification; it is excluded from this PR.
The single Ubuntu/Python-3.12 CI lane is narrower than `requires-python >=3.12`.
No failure on a later Python version is asserted without running it.

Current effective GitHub rules were accessible and checked, not assumed:

| Control | Observed value |
| --- | --- |
| Active [ruleset 25751574](https://github.com/TechTradeExpress/Diatonic-Orchestrator/rules/25751574) | Default branch target; active |
| Pull Request requirement | Enabled |
| Required approving reviews | **0** |
| CODEOWNER / last-push approval / stale dismissal / resolved threads | Not required |
| Required status | `lint-and-test` (integration 15368) |
| Strict up-to-date requirement | False |
| Non-fast-forward and deletion | Blocked |
| Bypass actors | Empty; querying user `current_user_can_bypass: never` |
| Legacy protection endpoint | 404; this does **not** mean the effective ruleset is absent |

The workflow limits token permissions to contents read and runs Ruff/pytest on PRs
and main pushes. A PR plus CI is technically enforced; independent approving review
is procedural, not enforced by the current zero-approval rule. Other organization,
account security and administrative controls were not audited. Nothing was changed.

## 9. Numbered findings

### M2-AUD-001 — P1: full-fidelity configuration is not a secret-safe boundary

**Evidence:** [ProviderSpec.config](../../src/diatonic/model/provider.py#L12),
[normalization/export](../../src/diatonic/compiler/normalize.py#L84), normative
[§21](../resource-model/v0alpha1.md#21-secrets), and Proposed ADR-0018. Existing
[opaque-config](../../tests/test_provider_model.py#L281),
[export isolation](../../tests/test_provider_model.py#L468) and
[CLI omission](../../tests/test_provider_model.py#L518) tests corroborate retention
and narrower presentation safety.

**Reproduction:** parse the following synthetic declaration with `parse_resource`,
wrap through the real loader/resolver, then call `normalize_resources(index)` and
both IR exports. The marker remains in both. No real credential is needed.

```yaml
api_version: iac/v0alpha1
kind: Provider
metadata: {name: audit}
spec:
  driver: example.driver
  config: {credentials: {token: PUBLIC_SYNTHETIC_NONCREDENTIAL}}
```

**Impact:** generic schema success cannot certify the normative prohibition on raw
secrets. Library exports may disclose retained data if used as telemetry. This is
not a demonstrated CLI config leak or a new regression; ADR-0018 already identifies
the gap. No runtime exists to reproduce transport/backend enforcement.

**Action/acceptance:** before any real-secret materialization or real adapter,
approve a driver-bound configuration classification contract, fail-closed preflight,
reference-only sensitive fields, and a dedicated allowlisted/redacted public
projection. Tests must prove tainted values cannot reach diagnostics, exports
intended as safe telemetry, child arguments/environment or error projections.
Do not silently change full-fidelity IR or rely on key-name heuristics. A synthetic
fake using no sensitive configuration can proceed only under the narrower gate.

### M2-AUD-002 — P1: independent review is not an enforced merge requirement

**Evidence/reproduction:** read ruleset `25751574` and effective main rules with
GitHub API (appendix). `required_approving_review_count` is zero despite the
[collaboration policy](../contributing-workflow.md) requiring human review/merge
control. PR/CI and no-bypass protections are positive current controls. This is a
policy-enforcement gap, not evidence that a particular merge was unauthorized.

**Impact:** a green PR can satisfy the observed rules without a formal approving
review, important before introducing subprocess/authorization code. No settings
were modified, and no test merge was attempted.

**Action/acceptance:** before merging affected runnable M3 code, the maintainer
must choose an enforceable independent approval rule (normally at least one
qualified approving reviewer), or explicitly accept a documented compensating
SHA-bound human review gate where account topology prevents formal approval.
Record who may approve and merge; verify effective settings after any authorized
change. This audit cannot approve its own gate or substitute for human acceptance.

### M2-AUD-003 — P2: optional typing currently fails

**Evidence/reproduction:** `uv run mypy src/diatonic` produces 29 errors/13 files.
Examples: [base spec](../../src/diatonic/model/base.py#L20) versus
[VM spec override](../../src/diatonic/model/virtual_machine.py#L79),
[resolution typing](../../src/diatonic/compiler/provider_resolution.py#L608),
and missing `types-PyYAML` for [loader imports](../../src/diatonic/compiler/loader.py#L7).
Runtime schema/regression tests pass; this is not a claim those models accept
invalid YAML.

**Action/acceptance:** agree a typing scope/configuration, resolve or narrowly
justify the current errors, supply supported stubs, then add an intentional check
in a separate PR. Avoid suppressing the entire compiler or redesigning public
schemas merely to appease a type checker.

### M2-AUD-004 — P2: reproducibility and supported-version evidence are limited

**Evidence/reproduction:** [pyproject.toml](../../pyproject.toml) uses dependency
ranges and Python >=3.12; no lock is tracked. [CI](../../.github/workflows/ci.yml)
resolves at runtime and tests only Ubuntu/Python 3.12. `uv sync` creates a new lock.
This is a reproducibility/coverage limitation, not a demonstrated dependency or
newer-Python incompatibility.

**Action/acceptance:** choose/document an application lock versus deliberately
floating dependency policy, with a reproducible CI lane and a controlled update
strategy. Define supported Python versions and add a proportionate compatibility
matrix or narrow the documented support promise after review. Preserve an upgrade
lane so locking does not conceal future breakage.

### M2-AUD-005 — P2: literal Rich rendering retains terminal-control sequences

**Evidence:** [name syntax](../../src/diatonic/model/types.py#L9) rejects whitespace
and slashes but permits ESC; [graph output](../../src/diatonic/cli.py#L308) and
[explain output](../../src/diatonic/cli.py#L400) pass resource identities through
`Text`. Existing [bracket safety tests](../../tests/test_cli_graph.py#L540) establish
markup safety, not control-character safety.

**Reproduction:** create a Stage with `metadata.name = "demo" + chr(27) + "[31m"`
and order zero; write it with `yaml.safe_dump`. Run both `graph FILE` and
`explain NAME FILE` using `CliRunner`, with `NO_COLOR=1`, `TERM=dumb`, and
`FORCE_COLOR` unset. Both exit zero with empty stderr. Captured output contains
exactly `Stage/demo\x1b[31m` (the representation here is escaped; the actual output
contains byte 0x1b). This probe used a harmless SGR sequence and no real terminal
emulator. No RCE or credential exfiltration is demonstrated.

**Impact/action:** untrusted resource text can influence terminal presentation.
Add a reviewed presentation-boundary policy to escape C0/C1/ESC controls across
success and diagnostic paths, with tests distinct from Rich bracket tests.
Preserve existing identity semantics unless a separate schema change is accepted.
Future gateway diagnostics must use classified safe values rather than assume
`Text` sanitizes subprocess output.

### M2-AUD-006 — P2: progress and contributor wording lag the implementation

**Evidence:** [M2 progress](../milestone-2.md) still presents M2.9 as being added for
review although PR #37 is merged. The Network model's old syntax-validation
wording can be read without the later semantic layer; the PR template still asks
which Milestone 1 step is implemented. README correctly describes completed M2.

**Action/acceptance:** a separate minimal docs PR should reconcile status,
historical module descriptions and PR guidance with current offline boundaries.
Keep original roadmap acceptance criteria and deferred runtime scope intact.
No behavior or security guarantee changes are needed.

### M2-AUD-007 — Note: Project is in the broad model, outside typed dispatch

**Evidence/reproduction:** model §17 lists Project; `parse_resource` accepts seven
concrete kinds and rejects a Project declaration with `union_tag_invalid`.
[test_unsupported_kinds_fail_at_discriminator](../../tests/test_typed_resources.py#L106)
explicitly includes it. M1's five-kind scope and M2's Provider/Binding increments
do not implement a Project/defaults schema.

**Disposition:** a broad-contract coverage gap and intentional incremental deferral,
not a reason to invent Project defaults in this audit. Document the supported
subset clearly; any Project support needs its own contract/requiredness/interaction
review and tests. It does not block credential-free fake protocol design.

### M2-AUD-008 — Note: the index is not an immutable authorization snapshot

**Evidence/reproduction:** [IndexedResource/ResourceIndex](../../src/diatonic/compiler/references.py#L68)
retain models. Resolve a valid minimal VM, create IR, assign `spec.cpu.cores = -9`
on the indexed model, and normalize again: old IR stays valid/unchanged, new IR
contains -9. Identity mutation is separately caught by
[test_mutated_identity_is_rejected_with_source](../../tests/test_normalized_ir.py#L328).
Other guards and [stale-binding tests](../../tests/test_provider_resolution.py#L610)
catch selected detectable inconsistencies, not every valid historical change.

**Disposition/action:** documented library preconditions require successful,
unmodified resolver inputs (ADR-0006/0007/0012/0016). Do not advertise the index as
deeply immutable. Re-resolve edited inputs. Future runtime authority must use
validated detached OperationContext-like data and scope-bound permission, subject
to ADR-0019 approval; reopening these models after authorization is forbidden by
that proposal, not prevented by current code. No hypothetical race is asserted.

### M2-AUD-009 — Note: staged offline passes differ from the broad model pipeline

**Evidence:** normative §23 describes a broader compiler sequence including future
validation/provider concerns; actual [CLI composition](../../src/diatonic/cli.py)
resolves references before normalization, validates binding configuration links
separately, and performs selection only for explicit managed explain queries.
ADRs and tests document this staged design. `validate` intentionally does not
check cycles/Stage constraints or resolve managed Providers automatically.

**Disposition/action:** identify supported guarantees at each API/command instead
of claiming complete normative pipeline implementation. Any normative sequencing
clarification requires separate approval; no public model edits are proposed here.
No counterexample demonstrating incorrect accepted portable output from this
ordering was found. Runtime lifecycle policies remain deferred.

### M2-AUD-010 — Note: selector literals are narrower than metadata labels

**Evidence/reproduction:** metadata `labels: {team: "R&D"}` is valid, but the same
value under `spec.match.labels` fails [_exact_selector](../../src/diatonic/model/provider_binding.py#L12)
because `&` is reserved alongside `*?[]!=<>|`.
[test_unsupported_selector_grammar_is_rejected](../../tests/test_provider_binding.py#L209)
and ADR-0014 explicitly document this conservative subset.

**Disposition/action:** this is a deliberate reviewed grammar limitation, not a
matching-algorithm error or undisclosed fallback. Kind-only selectors remain valid.
If all literal metadata values must become selectable, separately approve a
literal-only grammar/escaping policy and exact-match regression tests. Do not
silently introduce wildcards, expressions or specificity scoring.

## 10. Ranked remediation recommendations

| Rank | Finding/gate | Narrow follow-up and acceptance |
| --- | --- | --- |
| 1 | 001, M3 real-secret boundary | Human acceptance of ADR-0018 direction; implemented fail-closed classified config/secret handling and safe projections before real credentials. Synthetic-only scope explicitly excludes them. |
| 2 | 002, review governance | Maintainer disposition of approval enforcement or explicit compensating SHA-bound review, verified before affected runnable M3 merges. |
| 3 | M3 launch gate | Approve ADR-0019/0020 implementation scope; implement/test immutable authorized context, admitted executable and bounded failure-safe gateway before first child launch. |
| 4 | 005 | Escape terminal controls at presentation boundary; success/error tests with raw ESC and literal bracket cases. |
| 5 | 003 | Establish a useful typing baseline and remove/justify each current error before enforcing it. |
| 6 | 004 | Document dependency lock policy and supported Python coverage; separate reproducible and upgrade checks. |
| 7 | 006 | Correct stale progress/template/docstrings without rewriting roadmap history. |
| 8 | 007–010 | Track unsupported catalogue, mutable-input preconditions, per-command guarantees and selector limitations; expand only through scoped reviewed work. |

These are proposals with acceptance criteria, not authorization to change settings,
implement M3 or create follow-up issues automatically.

## 11. M3 readiness gates

### Stable foundations to reuse

Reuse explicit typed resources, identity syntax, resolved references/provenance,
IR detachment, immutable binding/phase/selection facts, graph witnesses and Stage
logical ordering. Preserve current provider-free CLIs. Treat all source/config
text as untrusted and potentially sensitive. Reuse algorithms behind their input
preconditions, not mutable models as authority.

### Before a first synthetic subprocess

1. Human reviewers accept or revise this audit and Proposed ADR-0018–0020, with
   an explicit small implementation issue/PR scope and review gate (002).
2. Define a synthetic-only fixture/allowlist containing no Provider config, secrets,
   secret references, real endpoints, vendor tools or infrastructure privileges.
3. Implement a detached validated operation context and trusted scope-bound
   authorization/dispatch boundary. Neither PhaseRequest nor offline Provider
   selection, desired state, prevent_destroy or M2 support JSON is permission.
4. Admit a specific trusted fake executable without a shell; restrict arguments,
   environment, working directory and inherited descriptors. A subprocess alone
   is not a security sandbox; document platform containment limitations.
5. Implement the reviewed bounded protocol/framing/version/correlation state
   machine, classified result projection, timeouts/cancellation/termination/reaping,
   stderr/stdout budgets and no automatic retry. Test malformed/duplicate/oversized/
   truncated/extra/replayed messages, crashes, floods, wrong identity and cleanup
   failure before allowing a successful launch path.
6. Demonstrate no raw child output/config/secret data enters diagnostics or future
   telemetry; failure must not be mistaken for proof of no effects. No exactly-once
   claim or real operation may be introduced through the fake experiment.

These are future implementation entry/launch gates, not components this audit
claims already exist. Pure message/state-machine implementation and tests may be
reviewed before an executable launch is enabled. The current repository alone
satisfies none of the runtime authorization/containment gates.

### Additional gates for later real Providers

Resolve 001 with admitted driver-specific config contracts, secret backend and
materialization lifetime policy, redacted projections and taint tests. Separately
review real operation classification/destructive safeguards, environment
compatibility, deployment permissions, retry/indeterminate-effect handling and
state/journal requirements. `desired_state: absent` does not prove destruction;
`prevent_destroy: false` does not authorize it. No generic GO for real adapters is
provided. Project support, richer selectors, other Python/OS coverage and broader
runtime features may remain deferred if explicitly outside the approved scope.

## 12. Evidence appendix and command ledger

### History and baseline

Repository safety checks ran before source inspection: clean `git status --short`,
`git switch main`, `git pull --ff-only origin main`, clean status and
`git rev-parse HEAD`. The worktree is real. PR #44 is merged at the audited SHA,
Issue #43 is closed, ADR-0020 exists, and the fresh branch is
`docs/milestone-2-quality-audit`. No user changes were stashed/reset/discarded.

Milestone issue/merged-PR mapping was checked with `gh issue list --state all --limit 100 --json number,title,state,url` and `gh pr list --state merged --limit 100 --json number,title,mergedAt,mergeCommit,url`:

| Scope | Issues → merged PRs |
| --- | --- |
| M1.1–M1.8 | #2→#3, #4→#5, #6→#7, #8→#9, #10→#11, #12→#13, #14→#15, #16→#17 |
| M2.0–M2.4 | #18→#19, #20→#21, #22→#23, #24→#25, #26→#27 |
| M2.5–M2.9 | #28→#29, #30→#31, #32→#33, #34→#35, #36→#37 |
| Post-M2 design | #39→#40, #41→#42, #43→#44; #38 remains open during audit |

All milestone implementation issues in that mapping are closed. Relevant PR
history distinguishes corrected help/Markdown defects from current findings.
No issue/setting changes were made by this audit.

### Commands, outcomes and limits

Read-only source investigation used `rg --files`, `rg -n`, `cat`, `sed -n` and
`nl -ba` over the requested documents, all model/compiler/CLI modules, test files,
fixtures/examples, `pyproject.toml`, `.gitignore` and `.github` guidance/workflows.
An inline `python3` AST inventory enumerated all test functions and top-level
classes/functions with line numbers. Source excerpts/AST inventories are navigation
evidence, not executable proof. One navigation attempt using `python` failed
(exit 127, command absent); it was rerun with `python3`. Scratch scripts/logs stayed
under `/tmp`; no new tests or source files are included.

| Executed command or inspection | Outcome |
| --- | --- |
| Git safety/status/main pull/rev-parse/worktree verification, then `git switch -c docs/milestone-2-quality-audit` | Clean real checkout, exact baseline above, fresh audit branch. |
| `gh pr view 44` / `gh issue view 43` metadata inspection | Merged/closed; ADR-0020 present. |
| `gh pr list` / `gh issue list` with fields above | Milestone/history mapping above; audit open. |
| `gh api 'repos/TechTradeExpress/Diatonic-Orchestrator/rulesets?includes_parents=true'` | Active repository ruleset discovered. |
| `gh api repos/TechTradeExpress/Diatonic-Orchestrator/rulesets/25751574` | Effective settings, no bypass and zero approvals recorded. |
| `gh api repos/TechTradeExpress/Diatonic-Orchestrator/rules/branches/main` | Effective default-branch rules confirmed. |
| `gh api repos/TechTradeExpress/Diatonic-Orchestrator/branches/main/protection` | 404 for legacy protection; not absence of ruleset. |
| `gh run view 40176630237 --json headSha,status,conclusion,url` and run-log inspection | Exact main SHA, completed/success; Ruff passed, 1,424 tests in 12.91s. |
| `/tmp/uv-x86_64-unknown-linux-gnu/uv sync --group dev` | Success; resolved 26 packages in 329ms, checked 25 in 1ms; generated lock excluded. |
| `/tmp/uv-x86_64-unknown-linux-gnu/uv run ruff check .` | Success: All checks passed. |
| `/tmp/uv-x86_64-unknown-linux-gnu/uv run pytest -q` | Success: **1,424 passed in 15.52s**. |
| `/tmp/uv-x86_64-unknown-linux-gnu/uv run mypy src/diatonic` | Optional check failed: 29 errors/13 files/28 checked; no suppression or installation attempted. |
| Python/interpreter and installed-distribution version inspection | Local Python 3.12.3; versions below. |
| `uv run python /tmp/m2-audit-probes.py` using the explicit uv path | All synthetic config/index/Project/selector/CLI probes and 800 bounded oracle cases passed their assertions. |
| Inline real-pipeline CliRunner ESC probe, color disabled | Graph/explain exit 0, stderr empty, raw user ESC retained. |

Local installed versions were Pydantic 2.14.1, PyYAML 6.0.3, Typer 0.27.3,
Rich 14.3.4, pytest 9.1.1, Hypothesis 6.170.9, Ruff 0.17.2 and mypy 1.20.2.
No lock or environment artifacts are committed. CI's newer Python patch is
reported separately rather than misattributed to the local run.

The independent Stage probe used `derandomize=True`, `database=None`, no deadline,
1–6 vertices, ranks from unassigned/-1/0/1, generated DAG subsets and a dense
cross-rank precedence oracle. The Provider probe used up to six candidates,
priorities -2..2 and supported/unsupported/unknown declarations; enumerating all
unknown completions identified whether the winner/tie outcome was invariant.
These inputs are bounded and synthetic. They do not contact or instantiate a driver.

### Minimal library reproduction pattern

This pattern uses the existing interfaces, not a parallel parser. Supply the
synthetic YAML from finding 001 in an owned temporary directory:

```python
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.references import resolve_resources
from diatonic.compiler.normalize import normalize_resources

index = resolve_resources(load_yaml_files([path]))
ir = normalize_resources(index)
assert "PUBLIC_SYNTHETIC_NONCREDENTIAL" in ir.to_json()
assert ir.to_dict()  # Full data is exported; inspect Provider spec.config.
```

For 008, use a valid VM with CPU/memory one, retain `old = normalize_resources(index)`,
assign `index.resources["VirtualMachine/app"].resource.spec.cpu.cores = -9`, then
compare old/new exports. The old snapshot stays unchanged; the new one reflects
the unsupported mutation. Do not treat mutation as a supported resource-edit API.

### Documentation verification

Final verification records are appended below before delivery. Only this report
is staged; production/test/schema/CI/ADR files are unchanged. Markdown validation
must check rendered structure as well as delimiter balance; neither passing
Python tests nor balanced backticks alone proves valid Markdown.

Final documentation checks: local `markdown_it` parsing and GitHub's
`POST /markdown` GFM renderer both succeeded (five tables, 32 headings). Rendered
HTML was inspected for table structure (two-, three- and five-column tables),
code spans and headings; this is structural rendering validation, not a browser
visual/accessibility audit. Relative file links and referenced line ranges were
checked against the checkout; code spans/fences balance, final newline is present,
and no raw ESC or malformed `»` delimiters occur. An initial per-line delimiter
check flagged two valid multiline command spans; they were made single-line and
checks rerun successfully. Synthetic examples contain no real credentials,
private endpoints or infrastructure data. Existing normative anchor references
were checked against their section headings.

`git diff --check` passed. Staged `git diff --name-only`/`--stat` inspection confirms
exactly this documentation file. The generated untracked `uv.lock` was removed,
not committed. Required code checks above were not rerun merely for prose edits;
no production/test inputs changed after they passed. Push/Draft-PR delivery does
not constitute approval, issue closure or merge.
