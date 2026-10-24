# ADR-0018: Provider configuration and secret security boundary

- **Status:** Proposed; human approval required before implementation.
- **Date:** 2026-10-24.
- **Evidence baseline:** `2b909f768210e104cb6324fb69a72a1b391e9180`, main after
  merged PR #37. No code, tests, CI, Resource Model or namespaces change here.
- **Scope:** Security design gate between the existing offline compiler and future
  execution. This ADR does not authorize an M3 implementation.
- **Related work:** [Issue #39](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/39)
  and the still-open [M2 audit #38](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/38).
  This narrow follow-up does not complete, accept or close that audit.

## Context

### Normative requirements versus implemented guarantees

[Resource Model §21](../resource-model/v0alpha1.md#21-secrets) prohibits secret
values in resource configuration and permits references instead. Its conceptual
example is:

```yaml
credentials:
  token:
    secret_ref: proxmox/main
```

This is the normative illustrative reference, not a credential or live backend
location. §21 leaves the backend separate; its environment-variable recommendation
is not an implemented feature or a requirement to inherit an entire environment.
§§10–12 distinguish ownership, explicit phase demand, capabilities, bindings,
Provider instances and drivers. §§14–15 describe normalized results and a future
language-neutral process boundary without choosing JSON Lines versus JSON-RPC.
§§22–23 and 31–33 leave runtime safety, journal and protocol decisions for later
milestones. This ADR preserves those distinctions and both API namespaces.

The generic schema does **not enforce the complete §21 prohibition**. That is an
identified enforcement gap, not permission to store plaintext secrets. A successful
M2 parse or selection cannot certify absence of secrets or execution readiness.
No existing CLI disclosure of Provider configuration is asserted here.

### Implementation evidence

| Current symbol | Observed behavior and limit |
| --- | --- |
| [ProviderSpec.config](../../src/diatonic/model/provider.py) | Required `dict[str, JsonValue]`; strict JSON-compatible types and finite numbers, but arbitrary nested keys/strings. No provider-aware sensitive-field contract. |
| [LoadedDocument / load_yaml_file](../../src/diatonic/compiler/loader.py) | Safe, strict YAML decoding yields mutable data. Parsing is neither confidentiality enforcement nor secret resolution. |
| [ResourceIndex / resolve_resources](../../src/diatonic/compiler/references.py) | Detaches input data and stores mutable Pydantic resources in a read-only index. Schema errors omit Pydantic input values from the selected diagnostic; retained objects and exception chains are not a redacted representation. |
| [normalize_resources / NormalizedResource / NormalizedIR](../../src/diatonic/compiler/normalize.py) | Serializes complete declared resource data with `mode="json", exclude_unset=True`; retains Provider config in canonical JSON. `NormalizedIR.to_dict()` and `.to_json()`, and per-resource exports, return full data without redaction. Detachment and immutability protect consistency, not secrecy. |
| [ProviderBinding / ProviderBindingSpec](../../src/diatonic/model/provider_binding.py), [validate_provider_bindings / ValidatedProviderBindings](../../src/diatonic/compiler/provider_bindings.py) | Validates exact Provider targets and snapshots selectors/priority/provenance. No configuration validation or secret handling. `spec.provider` remains a configuration link, not an infrastructure edge. |
| [analyze_phase_request / PhaseAnalysis / DriverSupportMetadata](../../src/diatonic/compiler/capabilities.py) | Explicit query only; preserves managed/external/disabled/unspecified ownership. Support descriptors assert capabilities, not trusted executable identity, config contracts or credential readiness. |
| [resolve_phase_provider / ProviderResolution / _evaluate](../../src/diatonic/compiler/provider_resolution.py) | Reads matching Provider driver IDs, never config; retains detached selection/candidate facts and provenance. Static support/priority selection performs no runtime authorization. |
| [validate / graph / explain](../../src/diatonic/cli.py), [explanation_text / resolution_error_text](../../src/diatonic/cli_explain.py) | Current human output selects counts, relationship/lifecycle facts and explicit phase/candidate details; does not dump Provider config or extensions. Literal Rich rendering prevents markup interpretation, not secret disclosure in arbitrary text. |

Evidence includes these existing tests, not new security tests in this PR:

- [test_provider_model.py](../../tests/test_provider_model.py):
  `test_unknown_spec_fields_fail_but_opaque_config_fields_survive`,
  `test_provider_yaml_roundtrip_isolated_graph_and_exact_secret_preservation`,
  `test_normalized_config_is_deterministic_detached_and_exports_are_fresh`, and
  `test_provider_only_cli_outputs_and_no_config_disclosure`.
- [test_provider_binding.py](../../tests/test_provider_binding.py):
  `test_immutable_summary_no_mutation_and_detached_provenance`.
- [test_capabilities.py](../../tests/test_capabilities.py):
  `test_no_provider_configuration_is_in_phase_results_or_errors`.
- [test_provider_resolution.py](../../tests/test_provider_resolution.py):
  `test_deep_immutability_detached_inputs_and_no_config_retention` and
  `test_configuration_is_never_inspected_even_on_errors`.
- [test_cli_explain.py](../../tests/test_cli_explain.py):
  `test_no_files_written_no_executable_config_or_environment_discovery`.

A local scratch check used only a publicly described synthetic noncredential
marker as a credential-like config literal: parsing succeeded and both IR exports
preserved it. No real credentials or infrastructure were used. This confirms the
retention gap; it does not establish a CLI leak. Metadata names, labels, paths,
selector comparisons, parser errors, object representations and arbitrary Python
tracebacks are not universally redacted. Users must not put secrets there either.

Related accepted implementation boundaries are documented in
[ADR-0013](0013-provider-instance-schema.md),
[ADR-0014](0014-provider-binding-declarations.md),
[ADR-0015](0015-offline-capability-phase-analysis.md),
[ADR-0016](0016-offline-provider-resolution.md) and
[ADR-0017](0017-explain-cli.md). Their milestone-specific deferrals are historical;
none provides a secret backend or execution security boundary.

## Decision

The following **D1–D6 are proposals for future implementation**, subject to review.
The §21 prohibition already applies; the mechanisms below are not implemented.

### D1. Keep offline compilation separate from privileged invocation

M1/M2 never materializes secrets. Keep current parsing, binding checks, graph,
phase analysis, selection facts and full-fidelity IR unchanged. Do not add backend,
installed-driver or execution-config requirements to `validate`, `graph`, baseline
`explain`, or its existing offline phase queries. An explicit M2 `PhaseRequest`
is an analysis query, not an execution request or authorization token.

Introduce a separate future execution-preflight boundary. A static selected
Provider is **not cleared for execution**. Desired state, prevent_destroy,
Stage/dependency order and `declared_supported` do not authorize an operation.
Runtime operation authorization and destructive safeguards remain separate gates.

### D2. Prefer trusted provider-specific data contracts over heuristics

Preferred direction: a declarative configuration contract associated with the
exact admitted driver implementation/version. Core applies generic validation and
security classifications; provider authors describe their own config structure.
There must be no `if vendor`/engine branches in core and no driver execution/import
just to obtain that contract. How contracts are packaged, authenticated/admitted
and bound to implementations needs separate review; driver ID equality alone is
insufficient. M2 support descriptors and local support JSON are not such contracts.

The future execution contract must account for every field that can be forwarded,
including nested lists/maps and permitted additional properties. Distinguish
ordinary declared JSON fields from secret-reference fields. At a declared secret
field, prefer the existing conceptual **reference-only** object: exactly
`secret_ref` with a nonempty reference string; reject inline scalar credentials,
extra payload members and invalid/ambiguous reference forms. Backend-specific
reference grammar, optionality and version selection require explicit contracts.
A required secret cannot have a plaintext or ambient-environment fallback.

Unclassified fields must not pass through as arbitrary opaque execution config.
Reject unknown fields or require an explicitly reviewed classification for a
contract's extension containers. A `secret_ref`-looking mapping outside a declared
reference field is not automatically a lookup instruction; reject ambiguous use
at preflight. This rule does not reinterpret opaque M2 data or create graph edges.

Key-name lists (`password`, `token`, `secret`), regular expressions, entropy tests
and blanket Pydantic secret wrappers cannot prove that arbitrary JSON is safe.
A contract can enforce reference syntax at declared sensitive paths; it cannot
prove that a user has not put a credential into an ordinary string, name or URL.
§21 still constrains users, and reviewed contracts must avoid permitting inline
credentials disguised as ordinary settings. Contract admission is a trust decision,
not a universal automated secret detector.

The first contract design can validate a selected config at a new internal runtime
boundary without changing current `ProviderSpec`. Any universal reinterpretation
of `secret_ref`, new YAML keys/types, reference grammar applying to all resources,
or stricter public Provider schema needs a separately reviewed Resource Model/API
proposal and compatibility tests. This ADR makes none of those changes.

### D3. Fail closed before provider invocation; resolve secrets late

For a future explicitly authorized managed operation, preflight must:

1. Bind the request to its exact resource, phase/capability, Binding, Provider
   instance, driver implementation/version and configuration contract. Own a
   detached invocation-input snapshot; detect/revalidate changes before dispatch.
   Do not reopen mutable `ResourceIndex` models after approval and silently send
   different config, or reuse one Provider instance's credentials for another.
2. Require unambiguous static selection plus trusted, compatible runtime metadata
   and the admitted configuration contract. Validate the operation's required
   config and reference-only sensitive fields. M2's user-supplied support assertion
   alone is not this evidence. Missing/incompatible/unknown required information
   rejects execution; never select an arbitrary fallback Provider or driver.
3. Check the caller's authority for the intended operation and required secret
   references. Only a late core-controlled materialization adapter may request
   those exact references from an approved backend. No lookup in YAML parsing,
   normalization, matching, graph construction, formatting or ordinary logging.
4. If a required reference, authorization, backend or resolved value is absent,
   invalid, unavailable or incompatible with the contract, reject before provider
   invocation. Do not substitute empty strings, plaintext YAML, cached unrelated
   values, environment expansion or another backend. On partial resolution failure,
   release any already obtained material without producing an executable request.
5. Assemble a minimal private invocation payload for that one Provider/operation,
   with secret material separate from the original resource snapshot. Do not
   mutate/cache secrets in IR, resource models, binding facts or selection results.
   Passing this security preflight is necessary, not sufficient: later operation
   and destructive-effect checks still apply before any infrastructure action.

An operation whose reviewed contract requires no credentials, such as the initial
synthetic fake-provider experiment, needs no secret backend. Optional credentials
must not trigger speculative lookup. External/disabled/unspecified analysis must
not be silently upgraded into a managed execution request.

### D4. Require a distinct redacted projection before user-facing exports

Keep `NormalizedIR.to_dict()`/`.to_json()` and per-resource serialization
full-fidelity. They are callable internal library exports, **potentially sensitive**,
not an authorization to publish portable data. Portable means independent of input
layout; it does not mean public, encrypted or redacted. No API behavior changes now.

A dedicated, explicitly named public/diagnostic projection is required before
future telemetry, journal serialization, machine exports or generic resource
logging. Prefer an allowlist of reviewed structural facts over copying then
blacklisting keys. Default to omitting entire Provider config, opaque extensions,
secret references and unclassified free-form fields. Any finer projection requires
an approved contract and tests; sensitive values must remain excluded recursively.
Redacting only known sensitive keys would leave the present opacity gap intact.

Public metadata may include a bounded request/trace identifier, resource/Provider/
Binding identity, phase, capability and stable status/error codes, subject to the
recipient's access policy. Such fields are not credentials by design, but can
still reveal deployment details and must not contain secrets. Raw labels, source
paths, exception messages, output values and reference identifiers are not
implicitly safe telemetry. Future journals/exports must store only the approved
projection; never full requests, raw responses, plaintext secrets, config dumps or
secret-derived hashes. Persisting sensitive provider outputs would require a
separate design, not an exception hidden in a journal serializer.

Normal CLI diagnostics/logs/traces must never contain plaintext secrets. Keep allowlisted, value-free field paths and error codes instead of raw
validation inputs, model repr, chained exceptions, request bodies or traceback
locals. Escaping Rich markup and returning detached dictionaries are not redaction.
Debug mode must not bypass this policy. Value matching may be defense in depth,
not the primary guarantee for encoded, transformed or previously unknown secrets.

### D5. Treat subprocess IO as privileged, untrusted data

Prefer passing the minimal private payload through a dedicated inherited channel
with restricted access, not shell interpolation, command-line arguments or general
environment variables. No entire-index/IR upload, argv config, secret-bearing
flags or ambient environment inheritance. Build an explicit minimal environment
and close unrelated file descriptors. A future environment-backed secret adapter
would read only authorized host values and deliver them through the private
payload; it would not expose the host environment wholesale to a provider.

The permitted request has separable nonsecret control metadata and privileged
configuration/secret material. Both may share a reviewed framed transport; they
have different logging/access policies. Request bodies must never be echoed or
included in ordinary traces. A local pipe alone is not encryption, a sandbox or
protection from a debugger/privileged host. This ADR does not choose JSON Lines,
JSON-RPC, framing, field names or a wire version; §15's transport question stays
open under the unchanged `iac-provider/v0alpha1` namespace.

Capture provider stdout/stderr privately with size/time bounds. Do not forward
raw stderr to the terminal or treat stdout as inherently trusted JSON. Validate
framing, shape, correlation to the operation and output classifications before
accepting normalized results. The permitted response must not return credential
values in outputs, diagnostics or tracebacks. A buggy/malicious process may still
emit them: treat all raw output as potentially sensitive, discard disallowed
payloads and publish a bounded generic error. Do not archive failed raw messages
for debugging. Generated secret outputs need a future separate handling contract;
ordinary result/journal paths must reject them.

Avoid secret-bearing temporary files by default. If a later adapter genuinely
requires one, a separately reviewed exception must specify private permissions,
exclusive creation, containment, bounded lifetime and cleanup on success/error/
timeout; unlinking is not proof of secure erasure. No credentials in crash reports,
core dumps, tracing attachments, CI artifacts or child environment/argv dumps.

Limit materialization to one invocation, prevent shared caches, release references
and close channels on success, failure, cancellation and timeout. Avoid unnecessary
copies, but do not promise reliable zeroization of Python strings, serialized
buffers, OS memory or storage. Host access controls, dump/swap policy, credential
scope/lifetime and provider trust remain necessary deployment controls. A provider
that legitimately receives a secret can misuse it; process separation alone cannot
stop malicious code running with equivalent host access or authorized network
access. Unadmitted providers must receive no secrets.

### D6. Start M3 with synthetic nonsecret messages only

The initial fake provider must require no real credentials, backend, endpoint,
installed vendor driver or infrastructure permissions. Use conspicuously synthetic
markers with no authentication value for transport/error-isolation tests. Reject
requests to turn the fake experiment into real operations; do not delegate to
shell commands, installed adapters or implicit network activity. Secrets and real
infrastructure remain blocked until the separate entry criteria below are met.

## Trust Boundaries and layer responsibilities

“May contain” records actual exposure or permitted privileged handling, not
permission to violate §21. Future “must” statements refer to proposals D1–D6.

| Representation / owner | Sensitivity and permitted handling | Boundary / status |
| --- | --- | --- |
| Raw YAML and `LoadedDocument` / author and loader | §21 requires references, never plaintext secrets. Actual untrusted input may violate this; identifiers/reference paths can also be confidential. | Current syntax checks do not certify confidentiality. Do not execute/interpolate input or treat it as safe to log. |
| Pydantic resources and `ResourceIndex` / compiler | May retain illicit literal secrets, arbitrary config and sensitive metadata. Internal mutable resource instances, not sanitized objects. | Current validation/detachment is not declassification; no materialized backend values belong here. |
| Normalized IR and portable full serialization / compiler consumer | May contain the same sensitive declared data in immutable JSON and detached exports. Internal, privileged full-fidelity view. | Current exports have no redaction; D4 requires separate future public projection. |
| Offline phase/Binding/selection facts / M2 analyses | No Provider config or resolved secrets retained. Identity, selectors and provenance can still be confidential/misused by the author. | Current static facts are not runnable requests, credentials or globally public telemetry. |
| Execution preflight and materializer / future trusted core layer | May briefly hold validated config and authorized resolved secrets in private invocation scope only. | Proposed fail-closed gate; never write them back into compiler objects. |
| Request control metadata / future protocol adapter | Must contain no plaintext secrets or opaque config; only reviewed bounded control facts. | Proposed allowlist; not a wire schema frozen here. |
| Private invocation body / future selected, admitted process | May contain only necessary selected config/secret material, never credentials for other Providers or the full index. | Proposed restricted handoff, not public/exportable request data. |
| Raw process responses/stdout/stderr / future IO gateway | Must be treated as potentially sensitive even if the allowed protocol forbids secret values. | Proposed capture/validate/drop policy; no direct passthrough or durable raw recording. |
| Human diagnostics/logs/traces / formatter and operators | Must not contain plaintext secrets, opaque config or raw request/response dumps. | Current CLI config omission is narrow; proposed public projections do not exist yet. |
| Journal, telemetry and machine exports / future persistence/export layer | Must not contain plaintext secrets; only explicitly approved projected facts/outputs. | Not implemented. No automatic use of full IR exports or provider logs. |

## Alternatives Considered

| Alternative | Decision and tradeoff |
| --- | --- |
| Opaque JSON plus key-name/regex masking | Rejected as primary control: sensitive strings need not have recognizable keys; innocent strings can trigger heuristics. May supplement a classified projection, never authorize dispatch. |
| Treat safe YAML, Pydantic strictness or immutability as sufficient | Rejected: these address syntax/types/consistency, not secret classification, access control or provider trust. |
| Globally wrap all config strings as secret or interpret every `secret_ref` | Rejected for M2: changes serialization/meaning, misses secrets encoded in other JSON shapes and can create unauthorized lookups from inert data. |
| Redact existing IR exports in place | Rejected here: breaks full-fidelity semantics, hides configuration from internal consumers and offers no complete classification for opaque values. Use an explicit projection instead. |
| Give providers backend access and let them resolve secrets | Not preferred: grants broader backend authority and weakens central per-operation scope/auditing. A trusted late core adapter offers one enforcement point; backend implementation stays separate, not a new secret store. |
| Forward arbitrary config to a selected driver for validation | Rejected as preflight: sends potentially sensitive data before validating the recipient and contract. Contracts must be available without invoking that driver. |
| Declarative per-driver contracts, late materialization, separate public projection | Preferred: testable generic core boundary without vendor branches. Costs contract maintenance, trusted admission and explicit refusal of unknown execution config; cannot detect every intentional misuse of ordinary strings. |

## Threat Model

Assets are credentials, secret-reference identifiers, opaque config, deployment
metadata and operation integrity. Consider mistakes, malicious YAML authors,
untrusted plugins and provider output. The known current exposure is retention of
opaque literals in library IR, not a demonstrated leak by the existing CLI. Future
rows are design hazards, not claims that a runtime already exists.

| Scenario / status | Mitigation and responsible layer | Future verification |
| --- | --- | --- |
| Plaintext in YAML / current generic validation gap | Author obeys §21; execution contract rejects sensitive literals; keep all unclassified input potentially sensitive. | Synthetic literals accepted by current generic schema remain blocked at future sensitive-path preflight. |
| Full IR written to stdout, logs or shared export / potential consumer misuse | D4 projection at export/log boundary; no implicit declassification by `to_dict`/`to_json`. | Sentinel absent from public projections and artifacts; full internal roundtrip unchanged. |
| Exception repr, parser detail or traceback leaks config / current surfaces are not a universal scrubber | Future privileged-error boundary publishes codes/paths, suppresses values, chained payloads and locals. | Inject nested/encoded markers through validation failures and crash reports; inspect every outward sink. |
| Provider echoes request to stdout/stderr / future hazard | IO gateway treats both as tainted, drops raw output, emits bounded error. | Echo, invalid framing, partial JSON and traceback fixtures never reach terminal/artifacts. |
| Required backend/reference unavailable or unauthorized / future hazard | Materializer rejects dispatch; no fallback or speculative lookup. | Denied/missing/expired inputs and partial resolution produce zero provider invocations. |
| Wrong binding/driver or cross-Provider config replay / future hazard | Preflight binds immutable input to exact instance, operation, admitted implementation and contract; revalidate changes. | Swap driver/config/identity after selection; mix same-driver instances; reject before material disclosure. |
| Malicious provider exfiltrates material / residual trust risk | Admission, least privilege and host isolation; deny secret handoff to untrusted code. Do not claim stdout filtering prevents exfiltration. | Fake process denied network/backend access; review real-provider permissions before secrets are allowed. |
| CI logs/artifacts capture sensitive payloads / future hazard | Synthetic-only fixtures; no real backend credentials; CI/output policies prohibit payload archives and environment dumps. | Failure/timeout jobs contain only synthetic safe diagnostics; inspect logs and artifacts. |

## Consequences

The offline compiler remains useful without credentials. Full-fidelity snapshots
remain deterministic, but callers must treat them as potentially sensitive; a new
redacted view and runtime boundary will be additional APIs, not hidden serializer
changes. Passing existing tests proves their specified behavior, not §21 compliance
for arbitrary config or future runtime secrecy.

Fail-closed preflight intentionally prevents execution when no reviewed contract
exists, including otherwise valid M2 selections. Contract and backend admission
require operational trust decisions. The core-controlled design reduces exposure
but cannot guarantee secrecy against a privileged host, malicious admitted driver
or deliberate secrets placed in nominally nonsecret fields. No heuristic solves
those residual risks. This decision is architectural guidance, not implemented
security hardening or a declaration that M3 is ready to run real providers.

## Verification Strategy

For this documentation PR: run the existing dependency sync, Ruff, full pytest and
whitespace checks; verify relative Markdown links and referenced symbols; manually
inspect the ADR for credentials, sensitive endpoints and claims of nonexistent
protection. Only this new ADR is committed. These checks do not exercise proposed
runtime controls; exact command outcomes belong in the PR description.

Before future implementation can claim these boundaries, add separate tests for:

- Contract coverage of nested objects/lists, unknown fields, reference shape,
  optionality, type errors and inline-secret rejection, without core vendor cases.
- Synthetic marker non-disclosure through public projection, object/exception
  formatting, validation details, protocol diagnostics, logs, telemetry and export
  paths. Test encodings/transformations; do not mistake substring filtering alone
  for a sufficient design or use real credentials to test it.
- Snapshot/operation binding, same-driver different-Provider isolation, stale
  config/metadata, missing/ambiguous support and wrong contract versions. No
  invocation or secret disclosure on any failed preflight.
- Denied/unavailable backends, invalid references, partial lookup failure,
  cancellation, expiry and cleanup. Offline commands must perform zero lookups.
- Fake process malformed/oversized/truncated/replayed messages, wrong correlation,
  invalid output types, stdout/stderr credential echoes, tracebacks, crashes,
  hangs/timeouts and cancellation. Prove bounded IO, termination/channel cleanup,
  no automatic retry into real operations and no raw output artifacts.
- Minimal argv/environment/descriptors, no payload temp files or unintended child
  processes, no network/real infrastructure access and no privileged fake-provider
  permissions. Tests need only synthetic values, never an actual secret backend.
- Existing full-fidelity IR, config-free M2 facts, explicit ownership semantics,
  deterministic CLI output and provider-free workflows remain compatible.

## Deferred Work

Proposed follow-ups only; this PR creates no additional Issues:

| Proposed follow-up | Required outcome / dependency |
| --- | --- |
| Trusted driver configuration/security contract design | Classification/unknown-field/reference semantics, exact driver/version binding and admission policy; no executable discovery required. Separate public-schema review if needed. |
| Invocation-input snapshot and execution authorization design | Define immutable operation scope, freshness and destructive-safety gates before runtime dispatch. Do not promote M2 PhaseAnalysis into authority. |
| Explicit redacted projection API | Default omission/allowlist rules, output classifications and non-disclosure tests before any public exporter/journal. Preserve current full IR APIs. |
| Late secret-materialization interface | Backend authorization, reference grammar, per-invocation lifetime, errors and cancellation; wrap approved backends rather than invent a store. Not required for synthetic fake M3. |
| Process IO and error-isolation design | Framing/limits, correlation, tainted output handling, environment/argv policy, temporary-file exceptions and host threat limits. Decide JSON Lines versus JSON-RPC separately. |

Still open: exact contract distribution/trust root, wire types/version negotiation,
backend selection/reference grammar, rotation/lease semantics, generated sensitive
outputs, platform sandbox controls and any legitimate need for provider-managed
secret retrieval. No solution is presumed deployed. Future exports and persistence
need their own recipient/retention policy; §22 does not authorize secret storage.

## M3 Entry Criteria

**Before starting the synthetic fake-process increment:** independently review this
ADR and the separate audit #38 conclusions; approve a narrowly scoped M3 protocol
and failure-isolation design. Define explicit synthetic requests/responses, IO
limits, safe error projection, minimal process permissions and prohibited real
operations. The fake provider must work with no secret backend or actual
credentials. This ADR alone is not that implementation authorization.

**Before any real-secret transport or real adapter:** implement and verify trusted
configuration contracts, exact invocation-input binding, operation authorization,
required compatibility checks, late scoped backend access, the redacted projection
and tainted stdout/stderr handling. Resolve the associated deferred gates and run
the negative tests above. Missing required evidence blocks invocation; a successful
M2 selection cannot waive a gate. Real destructive actions additionally require
separately reviewed planning and enforcement of `prevent_destroy` before execution.
