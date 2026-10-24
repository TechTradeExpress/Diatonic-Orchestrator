# ADR-0019: M3 operation intent, immutable context and authorization boundary

- **Status:** Proposed — requires independent human design approval before implementation.
- **Date:** 2026-10-25.
- **Evidence baseline:** `524e48718c7e21c0c5117d4116bd5ec9a9b2e67f» (merged PR #40).
- **Scope:** Documentation-only M3.0 design; no runtime, provider process, new public schema or operation authority is implemented.
- **Related work:** [Issue #41](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/41), open [M1–M2 audit #38](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/38), [ADR-0018](0018-provider-configuration-secret-boundary.md).
- **Authority:** [Resource Model v0.1](../resource-model/v0alpha1.md) remains normative. This ADR proposes internal policy where that document leaves choices open; it does not change `iac/v0alpha1» or `iac-provider/v0alpha1». ADR-0018 is merged but remains **Proposed**, and its safeguards do not yet exist. Issue #38 remains open and is **not** discharged here.

## Context and current guarantees

The completed M1/M2 system is a deterministic **offline analysis** engine, not an execution engine. It accepts strict YAML, creates a resource index and portable normalized IR, validates explicit and inferred references, builds a logical dependency DAG, computes offline Stage precedence, and analyzes an **explicit** lifecycle phase against bindings and caller-supplied driver-support declarations. No one of those steps requests, authorizes or performs an infrastructure action.

Current implementation evidence:

| Existing component | Verified role | Limitation relevant to M3 |
| --- | --- | --- |
| [`ResourceIndex» / `resolve_resources»](../../src/diatonic/compiler/references.py) | Read-only identity mapping with `IndexedResource» records and document-root provenance. | Its Pydantic resource instances remain mutable; it is not a historical freshness or authorization token. |
| [`NormalizedIR» / `normalize_resources»](../../src/diatonic/compiler/normalize.py) | Detached, deterministic full-fidelity JSON resource snapshots; provenance kept separately. | Contains opaque `Provider.spec.config» and possibly sensitive user data; `to_dict()»/`to_json()» are **not redacted exports**. |
| [`DependencyGraph»](../../src/diatonic/compiler/graph.py), [`StageOrderAnalysis»](../../src/diatonic/compiler/stages.py) | Immutable logical edges, reasons, Stage assignments and deterministic eligible order. | No operation nodes, runtime dependencies, executable sequence or authorization. |
| [`PhaseRequest», `PhaseAnalysis»](../../src/diatonic/compiler/capabilities.py) | Explicit `resource_identity + phase» analysis; preserves ownership origin, including omitted/null, and maps only documented managed pairs. | Analysis query ≠ executable intent; `managed» does not infer a verb. |
| [`DriverSupportMetadata»](../../src/diatonic/compiler/capabilities.py) | Supplied three-valued declaration: supported, unsupported or unavailable. | Not installation, environment compatibility, trusted implementation identity or readiness. |
| [`ValidatedProviderBindings»](../../src/diatonic/compiler/provider_bindings.py) | Immutable binding/Provider target summaries; exact selector and priority input. | Config link is not a DAG edge, driver admission or executable capability proof. |
| [`ProviderResolution», `resolve_phase_provider»](../../src/diatonic/compiler/provider_resolution.py) | Unique static selection or canonical trace/error; unknown potentially decisive support blocks choice. | Does not read Provider config, validate credentials, inspect environment or grant dispatch. |

Relevant regression evidence includes [`test_normalized_ir.py»](../../tests/test_normalized_ir.py) (detachment, omission/null), [`test_capabilities.py»](../../tests/test_capabilities.py) (explicit demand and support states), [`test_provider_resolution.py»](../../tests/test_provider_resolution.py) (selection, unknown support, immutable traces and snapshot mismatch checks), and [`test_stage_order.py»](../../tests/test_stage_order.py) (logical order and conflicts). Existing tests do not establish runtime authorization, time-of-use freshness or process safety.

The Resource Model [§10](../resource-model/v0alpha1.md#10-lifecycle) defines lifecycle phases `observe», `provision» and `configure», ownership `managed», `external» and `disabled», `desired_state: present|absent» and `prevent_destroy». [§13](../resource-model/v0alpha1.md#13-provider-interface) **separately** lists provider verbs `validate», `observe», `plan», `apply» and `destroy», not universally implemented. [§14](../resource-model/v0alpha1.md#14-provider-result-contract) illustrates a result but does not freeze a complete wire schema. [§15](../resource-model/v0alpha1.md#15-provider-protocol) wants a language-neutral process boundary while leaving framing open. [§21](../resource-model/v0alpha1.md#21-secrets) disallows inline secrets; [§22](../resource-model/v0alpha1.md#22-state-and-execution-journal) distinguishes eventual journal metadata from authoritative Terraform state; [§23](../resource-model/v0alpha1.md#23-compiler-pipeline) describes future full validation. Resource Model §§31–33 places a fake process before real adapters and deliberately leaves transport, outputs, import/deletion semantics and planning guarantees for further design.

[ADR-0009](0009-m2-dependency-lifecycle-boundaries.md) makes `desired_state: absent» and `prevent_destroy: true» a **valid static combination**; a later destructive effect must be blocked, while an already-absent resource may be a no-op. [ADR-0012](0012-stage-order-analysis.md) makes Stage ranks offline logical constraints, not phase scheduling. [ADR-0015](0015-offline-capability-phase-analysis.md), [ADR-0016](0016-offline-provider-resolution.md), [ADR-0017](0017-explain-cli.md) and [ADR-0018](0018-provider-configuration-secret-boundary.md) explicitly defer executing operations and privileged configuration handling.

## Glossary and boundaries

The following names and records are **proposals**, not currently implemented Python classes, YAML fields or protocol messages:

- **OperationIntent** — an independently authenticated caller's explicit wish to consider **one** `Kind/name», one lifecycle phase and one requested provider verb. It is a request to evaluate authorization, **not** authorization itself.
- **OperationContext** — a detached immutable candidate describing the exact resource, phase, verb, binding, Provider, driver and policy/configuration snapshot for this one request. Neither creating nor serializing it authorizes dispatch.
- **PreflightDecision** — a future trusted gate's explicit **allow/reject** on a particular context, operation, subject, evaluated effects and admitted driver/version. A generic `allow» without scope or freshness is invalid.
- **DispatchPermit** — an optional future *internal, single-use, scope-bound* handoff resulting from successful preflight **and** necessary operation/destructive-effect checks. Not a YAML token, not inferred from a phase analysis, not exported to plugins or the CLI. Its precise implementation remains an M3 follow-up.
- **Declared support** — M2 caller-supplied capability metadata; not trusted runtime compatibility.
- **Effect classification** — proposed characterization of the precise side effects of a provider request, especially destroy, replacement or collateral deletion; never inferred merely from the verb's name or desired state.
- **Invocation** — one attempt to contact an admitted provider process, distinct from the logical intent and from any retry or resume.

### Separation decision (P1)

Adopt this conceptual internal dependency direction for a future implementation:

~~~text
untrusted YAML -> M1/M2 compiler and offline analyses (no side effects)
                             |
authenticated caller -> explicit OperationIntent
                             |
                 freeze/revalidate exact inputs
                             |
                immutable OperationContext
                             |
 trusted policy + identity + compatibility + effect/secret preflight
                             |
           scoped permit for one approved attempt
                             |
            M3.1 protocol/IO gateway (later)
                             |
              synthetic fake process (later)
~~~

There is **no reverse dependency** from M1/M2 loading, normalization, dependency/Stage analysis, offline phase analysis, explain or static selection into the runtime. Graph order never automatically produces operation intents. A provider process receives neither `ResourceIndex» nor the complete `NormalizedIR». An author-controlled identifier, a YAML `managed» setting or `PhaseRequest» is not a privileged command.

## Decision: explicit OperationIntent (P2)

For the first M3 design, support a **single logical resource + one explicitly requested phase + one provider verb per intent**. No batch resources, implicit phase expansion or recursive processing of prerequisites. A caller explicitly requests all three coordinates; no absent values are filled from `desired_state», `Stage» or graph order.

Proposed minimum internal shape (illustrative only, **not** public or wire schema):

~~~text
OperationIntent:
  resource_identity: "VirtualMachine/demo"
  phase: "observe"                         # explicit M2 phase vocabulary
  verb: "observe"                          # explicit provider verb vocabulary
  caller_context: authenticated principal / authority reference (trusted)
  request_id: caller-visible correlation identifier, not an authorization secret
~~~

The requested verb is **not** derived from a lifecycle phase. The caller's identity is established outside YAML; self-declared usernames and metadata labels are not evidence. The authorization system must evaluate whether that authenticated subject may request the exact verb against this particular resource and Provider. The model's `desired_state» is declaration evidence, not a substitute for intent.

Malformed identity/verb/phase, unknown target or unsupported combinations reject the intent. Destruction requires its own explicit narrowly scoped request plus an independently reviewed effect/approval policy; an initial fake-only simulation must never be reusable as authority for real infrastructure.

## Decision: phase, verb and declared state (P3)

The following is an **internal design policy proposed for review**, not a claim that M2 implements verbs or that any concrete driver supports them. A pair marked "candidate" still needs operation-specific semantics, trusted compatibility, preflight and caller authorization; it is **not executable** on today's code.

| Phase or context | Explicit verb | Initial disposition | Important condition |
| --- | --- | --- | --- |
| `observe: managed» | `observe» | Candidate for synthetic, read-only fake experiment | Required documented observe capability and admitted driver; absence of state/defaults does not create another verb. |
| `provision: managed», desired `present» | `plan» | Candidate for nonbinding synthetic preview | Must declare an explicit preview guarantee; preview cannot be assumed equivalent among Terraform, Ansible or native APIs. |
| `provision: managed», desired `present» | `apply» | Deferred for real effects; **synthetic no-effect** experiment only after M3.1 | An explicit effect contract must distinguish creation/update/replacement; existing capability does not prove the verb. |
| `configure: managed» | `plan» or `apply» | Deferred until configuration-operation semantics are reviewed; synthetic proof only if expressly scoped | Do not assume a configure phase always maps to the same driver verbs or creates no destructive effect. |
| Any managed supported phase | `validate» | Separate preflight/driver-contract candidate, not automatically another lifecycle phase | Validation of config/protocol does not itself require managed action or grant authority; exact invocation requirements deferred. |
| `provision: managed», desired `absent» | `destroy» | **No automatic mapping; policy-gated explicit destructive intent only** | Observe actual state/effects, handle already absent, require explicit approval and check `prevent_destroy» before dispatch. |
| `provision: managed», desired `absent» | `observe» or `plan» | Only with separately reviewed phase/verb rules | No implicit phase request or destruction; unknown preview semantics must be visible. |
| Any `external» phase | Any mutating verb | Reject | Ownership outside orchestration; the declared resource may remain a logical prerequisite. |
| Any `disabled» phase | Any operation for that phase | Reject | Intentionally not applicable. |
| Any omitted/null/unspecified phase | Any executable verb | Reject | No ownership default; missing evidence cannot imply managed execution. |
| Any supported phase | Verb missing from trusted driver contract | Reject | The seven documented M2 capability pairs do not imply provider-verb support. |
| Managed `Image», `Stage», `Provider» or another undocumented phase/capability pair | Any verb requiring it | Reject | Preserve M2 `unsupported_managed_phase»; do not invent capability IDs. |

**Safety matrix for deletion and replacement:** `prevent_destroy: true» blocks any evaluated destructive effect, including a replacement that removes an existing object, regardless of whether the requested verb is named `apply». `prevent_destroy: false» or omitted/null is **not** authority to delete; explicit intent, caller policy, credible effect classification and fresh approval are still required. If the operation's effect classification is unknown, **reject a real mutating operation**; do not assume "apply" is harmless. `desired_state: absent» is a static desired outcome and may correspond to "already absent" (no-op), not automatically destruction. Removing a resource from YAML produces no operation. Any waiver/override mechanism requires a new ADR, not a magic flag.

`plan» is a proposed inspection verb with a driver-advertised *grade of guarantee*, not a universal faithful preview. A backend that offers only a partial check must not be described as producing a Terraform-equivalent plan. `validate» and `observe» are not interchangeable. For real infrastructure, read-only claims must be backed by trusted effect policy, not by vocabulary alone.

## Decision: immutable OperationContext (P4)

Proposed **minimal owned internal snapshot** of a single candidate invocation:

| Field/group | Required for intended future context | Sensitivity and role |
| --- | --- | --- |
| Exact canonical `Kind/name», phase, verb, requested capability | Yes | Portable control identity; still deployment metadata, never assumed safe for public logs. |
| Authenticated caller authority reference and `request_id» | Yes (trusted source, no plaintext credentials) | Internal identity and audit correlation; no public user credential or raw auth token. |
| Ownership and M2 omission/null origin | Yes | Preserve the exact phase declaration; only explicit `managed» can pass mutating preflight. |
| Declared `desired_state» and `prevent_destroy», including presence/null | Yes when relevant to safety evaluation | Preserve rather than default; no implied authority. |
| Exact ProviderBinding identity, selector/capability and priority snapshot | Yes for managed phase requiring selection | Bind to winner uniquely; does not itself grant execution. |
| Exact Provider **instance** identity, driver ID and selected config snapshot | Yes for future privileged invocation | Config is **sensitive internal**, not a public control record or log payload; same driver may serve distinct Provider instances. |
| Trusted driver implementation identity/version and admitted config contract identity/version | Required **before privileged invocation**; may be absent in rejected candidate | Separate runtime trust from user-supplied M2 support assertions. |
| Relevant resource spec/labels/extensions snapshot and evaluated declared references | Required only as inputs consumed by the proposed operation contract | Preserve exact bytes/typed values as needed; exclude unrelated resource config from process handoff. |
| M2 unique selection facts, capability support trace and immutable constraints | Yes as evidence when applicable | Caller-supplied support is **insufficient** runtime proof; trace kept outside privileged payload. |
| Detached source-root provenance (path/document/position) | Yes for trusted diagnostics only | Real locations are not field locations; do not put paths or secret-like metadata into public error projection. |
| Snapshot fingerprint/epoch and local construction metadata | Recommended internal comparison tools | Detect mismatches; hash neither authorizes nor makes sensitive input safe; no global revision system. |

The context **owns** all data it uses; no live Pydantic model, mutable `ResourceIndex» link, backing dict or caller list is retained. Separate a nonsecret *restricted control view* from a private, full-fidelity *invocation input* (which can contain opaque config/secret references). "Immutable" means recursive detachment and read-only ownership, not automatic redaction or guaranteed truth about external state. No context constructor may return a supposedly executable object with missing, ambiguous or unresolved binding/driver evidence.

### Freshness and TOCTOU policy (P4a)

Choose a **single-invocation freeze-and-revalidate** design, not global versions or an execution database:

1. Start with an explicit intent and successful full relevant M1/M2 passes over a coherent compiler input set. Ensure request ownership is managed; ask M2 for **only** the requested phase. Do not trust partial, corrupt or mixed snapshots.
2. Revalidate or reconstruct the relevant resource, binding and Provider instance against **one admitted input snapshot**; capture the exact selected identities, labels, binding priority, Provider driver/config, declared safety flags, trusted driver support/contract identifiers and permitted policy inputs. The first version may re-run existing validations over that coherent snapshot rather than introducing generalized compiler hashes.
3. Deep-copy/serialize-to-owned data once and produce frozen context facts, with a separate sensitive input area. Keep a scoped fingerprint for equality/change detection but never publish a digest of secrets as "safe" telemetry and never treat hash equality as proof of caller authorization.
4. Evaluate authorization and compatibility **against these owned facts**; never re-fetch arbitrary mutable index models after approval. Bind the permit to this exact context and chosen provider implementation, not only to `Kind/name».
5. **Immediately before dispatch**, verify that the permit and configured adapter refer to the same approved context, driver version, contract, Provider instance and effect policy; reject when the chosen inputs or evidence no longer match. External state may change after observation—do not claim this removes all races. A real operation needs separate concurrency/state-effect handling.
6. A changed label, priority, binding target, Provider driver/config, ownership, `prevent_destroy», contract version, admitted metadata or caller permissions invalidates the pending permission. Start a **new** intent/validation/authorization; never silently substitute a runner or reselect at dispatch.
7. Never reuse a Provider instance's credential scope for another Provider with the same `driver» identifier. Cross-Provider replay and stale metadata fail closed.

This policy avoids historical-freshness claims M2 cannot make. It does not turn serialized whole IR into a provider request, does not implement locks across hosts and does not promise atomic external observation.

## Decision: authorization, preflight and dispatch (P5)

These are **separate mandatory future gates**, and passing earlier steps is insufficient:

1. **Intent gate:** trusted caller identity, exact single-resource/phase/verb request, explicit managed ownership and supported M2 capability, with controlled rejection of unspecified or unsupported combinations.
2. **Static gate:** complete M1/M2 compilation including graph and Stage consistency, one unique binding with no decisive unknown support; do not replace a rejection with file-order fallback.
3. **Runtime trust gate:** verify admitted actual driver identity/version, provider protocol/verb support and the matching trusted declarative configuration contract. User-supplied `DriverSupportMetadata» from M2 never proves runtime trust.
4. **Context gate:** construct and freeze exact invocation input; verify binding/Provider/resource identity, labels, contract and freshness against the same snapshot; no mutable resampling after approval.
5. **Authorization/effect gate:** check caller privileges and operation-specific permissions. For real mutation, use explicit effect classification and reviewed destructive safety policy, including `prevent_destroy» at authorization **and** final dispatch. Unknown/partial effect classes cannot be presumed safe. Approval for preview does not authorize apply; fake-only simulation approval cannot authorize real actions.
6. **Configuration/secret gate:** apply ADR-0018's **proposed** trusted field-classification rules, reject unknown/invalid execution config and inline credentials at classified sensitive paths, authorize exact secret references, resolve them **only late** through an approved trusted backend when required. A synthetic fake with no credential contract performs zero lookup.
7. **Final dispatch gate:** bind single-use scoped permit to exact context, driver implementation, authorized effects and an invocation attempt; ensure no stale inputs, revoked authority or swapped provider. Dispatch **only** through separately reviewed M3.1 gateway. Never use Stage topology or success of `explain» as a substitute.

Until the corresponding runtime contracts/implementations are independently reviewed, all seven gates are **design requirements**, not existing enforcement.

Proposed **stable category names** for future structured, nonsecret rejections (not currently implemented public error codes): `invalid_operation_intent», `ownership_not_managed», `unsupported_phase_verb», `snapshot_mismatch», `provider_selection_unresolved», `runtime_support_untrusted», `driver_contract_unavailable», `authorization_denied», `operation_effect_unknown», `destructive_effect_blocked», `secret_preflight_unavailable», `dispatch_context_mismatch». An implementation must define deterministic precedence and structured safe context; never include Provider.config, secrets, raw YAML values, untrusted process stderr, exception repr or file bodies. Reuse existing M2 diagnostic **codes** for errors belonging to the M2 layer; do not relabel them as runtime policy failures.

## Single-operation flow and conceptual example

For a fictional `VirtualMachine/demo» explicitly declared `lifecycle.phases.observe: managed», an authenticated caller requests `observe». The following illustrative pseudo-process is **not a running API or protocol**:

~~~text
caller: intent(resource="VirtualMachine/demo", phase="observe", verb="observe")
  -> compile and validate one coherent offline input set
  -> analyze_phase_request(..., explicit observe) -> managed, required capability
  -> resolve_phase_provider(...) -> unique declared binding/Provider (static)
  -> freeze exact resource/binding/Provider/driver context (private)
  -> trusted runtime admission + verb/effect/contract and caller checks
  -> no-secrets synthetic preflight -> scope-bound one-attempt permit
  -> [future M3.1 only] fake-process request through restricted gateway
  -> validate correlation/schema/effects and return safe result projection
~~~

No prerequisite resource is implicitly executed. A real environment's prerequisite readiness is unknown; the initial fake exercise **only** demonstrates request validity, fencing and process failure behavior. For `desired_state: absent» with `prevent_destroy: true», a requested `destroy» is rejected before dispatch (unless a later separate policy explicitly changes the authorization model); for `external» or omitted ownership, the sequence stops before managed selection and privileged invocation.

## Failure, retry, timeout and result policy (P6)

- **Request identity** identifies the logical explicit caller intent; it is not a globally unique action key or a secret. **Invocation identity** identifies one concrete dispatched attempt; separate it from request/correlation identity and bind it to its frozen context and admitted process. The next attempt gets a fresh invocation ID.
- **Correlation** is required for accepting future process responses; the M3.1 protocol chooses type, framing and replay defenses. A response lacking matching invocation identity/version is rejected without broadcasting raw output.
- **Idempotency** is a driver/operation-specific semantic guarantee, not inferred from a retry token, deterministic context hash, `desired_state» or unchanged YAML. No exactly-once claim.
- **Crash, timeout, cancellation, malformed response or lost acknowledgement** may mean the provider produced effects before reporting. Report an **indeterminate** outcome when effects are unknown, not "success", "failed with no changes" or automatic rollback. Do not retry a possibly mutating real action without fresh authority, reconciliation/observation and an operation-specific idempotency design.
- **Cancellation** may stop local waiting and request process termination, but is not proof that remote effects were undone. Treat late/duplicate responses as untrusted and enforce request/invocation correlation at the gateway.
- **Retries** must be expressly requested/approved per attempt, especially for mutation/destruction. The synthetic fake may test explicit same-intent/new-attempt behavior without actual effects; generic auto-retries are out of scope.
- **Results** should eventually normalize outcome, changed/unknown effects, provider identity, phase, controlled diagnostics and approved outputs, taking [§14](../resource-model/v0alpha1.md#14-provider-result-contract)'s `resource», `phase», `provider», `changed», `external_id», `outputs», `diagnostics» as **illustrative**, not frozen wire fields. Empty/absent output and unknown outcomes need explicit semantics. No raw stderr/stack traces or unclassified output values in outward diagnostics. Persistent journal/state is not implemented or authorized here.

The first fake process may deterministically return synthetic success, declared no-change, a controlled rejection, malformed data or simulated crash/timeout. It cannot demonstrate external state reconciliation, exactly-once semantics, real destructive safeguards or cross-provider convergence.

## Threat model, data handling and alternatives

**Trust boundaries:** author-supplied YAML and user-supplied capability JSON are untrusted assertions; authenticated caller claims must come from a separate trusted source; full internal model/IR can contain sensitive Provider config; a selected driver string is not admitted executable identity. Raw provider stdout/stderr, return values and exceptions are untrusted. A restricted diagnostic projection is **proposed but not implemented** under ADR-0018.

| Risk | Proposed boundary / proof condition |
| --- | --- |
| Phase analysis reused as authority | No executable intent or permit generated from `PhaseRequest», graph or explain. |
| Same-driver/different-Provider credential replay | Bind context/permit to Provider instance, actual driver version, exact allowed config and operation. |
| Mutable index changes after selection | Freeze once and reject stale/mismatched inputs before dispatch. |
| Caller asks apply after preview authorization | Different verb/effect scope requires new authorization. |
| Real provider advertises capability but lacks compatible verb/contract | Reject; M2 caller-supplied support is insufficient. |
| Raw credential-like config appears in full IR | Treat whole IR as potentially sensitive; pass only reviewed minimal contract fields; do not log `to_json()». |
| Malicious process emits secrets in stderr or outputs | Capture as tainted, impose bounds, validate/omit, emit safe generic code; do not blindly relay. |
| Unknown replacement/destroy effect or stale safety policy | Reject real side-effecting dispatch and enforce `prevent_destroy» at the final boundary. |
| Replay of a previous permit, delayed response or retry | Proposed single-use permit and fresh attempt identity; robust correlation and expiry belong to M3.1. |

Alternatives considered:

| Alternative | Decision |
| --- | --- |
| Treat an M2 `PhaseRequest» or `ProviderResolution» as executable | **Reject:** phase is not verb, selected binding is not trusted/authorized runtime compatibility. |
| Automatically turn `desired_state: absent» into `destroy» | **Reject:** desired state can represent already-absent; no observed effect, approval or `prevent_destroy» bypass. |
| Map every `provision» to `apply» or every `configure» to a fixed verb | **Reject:** loses provider-specific guarantees and makes no-effect vs destructive changes invisible. |
| Pass mutable `ResourceIndex» or all `NormalizedIR» directly to provider | **Reject:** TOCTOU, information oversharing and full-fidelity sensitive Provider config. |
| Rely only on file/hash equality for a dispatch permit | **Reject:** matching bytes do not establish caller authority, installed driver trust or safe effects. |
| Let provider choose arbitrary Binding or retry another Provider | **Reject:** defeats deterministic ambiguity checks and credential isolation. |
| Build a full DAG/Stage/phase runtime scheduler now | **Defer:** single-intent scope tests trust and protocol boundaries without freezing parallelism and ordering prematurely. |
| Retry automatically after process failure | **Reject for real mutations:** uncertain effects and idempotency; synthetic retries require explicit separate attempt context. |

Consequences: the first runtime iteration will be intentionally narrow, with extra explicit gates and more rejected requests. It trades ergonomics for auditable authority. It does **not** address transactional cross-provider work, complete lifecycle convergence, adoption/import, removal-from-config semantics, persistent state/journal, distributed locks, policy-as-code, secret backend design or real-provider compatibility. Those remain separate decisions.

## Verification plan (proposed tests, not implemented in this PR)

A future focused M3 code PR should include at least these synthetic-only cases:

1. Explicit managed `observe» intent composes the exact M2 phase/selection result without silently selecting other phases; nonmanaged or unsupported phases fail before process spawn.
2. Distinct phases/verbs or case-different logical identities never share a permit. Wrong capability, wrong Provider instance, stale driver version or missing contract is rejected.
3. Alter resource labels, binding priority/provider, Provider config/driver, lifecycle `prevent_destroy», caller privileges and trusted metadata between analysis, freeze, authorization and dispatch: all relevant mismatches fail before side effects; existing snapshots remain immutable.
4. Missing/unknown/unsupported/tied driver metadata preserves M2's distinct errors. A declared-supported user descriptor alone never satisfies trusted runtime admission.
5. `desired_state: absent» alone requests nothing; `prevent_destroy: true» blocks synthetic-classified destructive effects, including replacement through a nominal `apply» verb. `false»/null/omitted never grants deletion authority.
6. Synthetic no-secret context makes **zero** backend lookups, does not log opaque Provider config, and never sends full IR to fake process. Two Provider instances sharing driver receive strictly isolated contexts.
7. Malformed or oversized request/response, wrong correlation, duplicate/replayed response, stderr echoes, exit failure, crash, timeout and cancellation produce bounded safe diagnostics without raw data, hidden retries or hanging processes.
8. A failed preflight leaves zero invocations and no leaked partial public context; request ID, attempt ID and public diagnostic projection are distinct.
9. All M1/M2 `validate», `graph», baseline/explicit `explain», portable IR serialization, omission/null and deterministic graph/Stage ordering remain byte-compatible in agreed fixtures.
10. Exercises run without real credentials, network endpoints, installed adapters or infrastructure changes; negative IO tests use conspicuously synthetic nonsecret markers.

These are **acceptance targets** only; no implementation, test or provider protocol exists as part of ADR-0019.

## Milestone gates and next ADR

| Gate | Required before advancing | Not implied |
| --- | --- | --- |
| **M3 design review** (this PR) | Independent review and human acceptance of the single-intent/context/authorization separation and explicit open questions. Issue #38 remains independently tracked; ADR-0018 remains a proposal unless separately accepted. | No process execution, provider protocol or new public model. |
| **Synthetic fake-process implementation** | Human disposition of the conclusions for open audit [#38](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/38); separate review of [ADR-0018](0018-provider-configuration-secret-boundary.md) and this ADR; approved M3.1 framing/error-isolation ADR; explicit synthetic-only/no-secrets/no-network scope, bounded IO and controlled negative tests. | No real infrastructure operation, no secret backend, no upgrade of static selection to runtime permission. |
| **Real-secret transport and real adapters** | Reviewed and implemented exact driver/version admission and config contracts; authorized late secret handling; immutable scoped snapshot/permit; safe output projection and process IO; credible effects, destructive policy, final `prevent_destroy», failure/reconciliation strategy and tests. | No promise of exactly-once semantics or universal backend planning. |

The **next separate ADR (M3.1 Provider Protocol & Error Isolation)** must decide: concrete language-neutral framing (JSON Lines, JSON-RPC or smaller bounded envelope), version negotiation within the unchanged namespace, process discovery/admission and lifetime, handshake and verb/capability advertisement, request/attempt correlation, duplicate/late responses, maximum message bytes and execution time, subprocess argv/environment/file-descriptor restrictions, stdout/stderr capture, crash/timeout/cancellation, malformed output and error projection. It must explicitly prevent a fake protocol demo from becoming a real invocation path by accident. This ADR **does not** choose transport, wire fields, transport auth or process implementation.

Open research/design questions: exact grades of preview guarantees; configure action semantics and required ordering; operation-effect classification and authoritative state observation; how a trusted contract is shipped and pinned to the driver; authorization subject/policy representation, approval/override handling, revoked permissions, transaction boundaries, external dependency readiness, planned retries, generated secret outputs and journal retention. None is solved by the present offline analyzer or this document.

**Implementation is not authorized by acceptance of this ADR alone.** No changes to existing source, tests, CI, README, M1/M2 roadmap, Resource Model, versioned namespaces or GitHub settings are made by this PR.
