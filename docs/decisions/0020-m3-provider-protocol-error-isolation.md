# ADR-0020: Synthetic Provider Protocol and process error isolation

- **Status:** Proposed; independent human design approval required.
- **Date:** 2026-10-25.
- **Evidence baseline:** `c9c9ed456fb9b5ec192220a55b77c9d1fd1841a3`, merged PR #42;
  Issue #41 is closed and ADR-0019 is present.
- **Scope:** One documentation-only design for a later nonsecret fake process.
  No parser, executable, runner, authorization, test or CLI change is implemented.
- **Tracking:** [Issue #43](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/43).
  [Audit #38](https://github.com/TechTradeExpress/Diatonic-Orchestrator/issues/38)
  remains open; this document neither completes nor modifies it.

## 1. Context, authority and evidence

[Resource Model v0.1](../resource-model/v0alpha1.md) is normative. Its
[§10](../resource-model/v0alpha1.md#10-lifecycle) phases and ownership,
[§13](../resource-model/v0alpha1.md#13-provider-interface) provider verbs and
[§14](../resource-model/v0alpha1.md#14-provider-result-contract) illustrative result
are distinct concepts. [§11](../resource-model/v0alpha1.md#11-capabilities) and
[§12](../resource-model/v0alpha1.md#12-provider-architecture) distinguish demanded
capabilities, drivers, instances and bindings. [§15](../resource-model/v0alpha1.md#15-provider-protocol)
requires a language-neutral boundary but leaves framing open. The JSON Lines
choice below is **this ADR's proposal**, not a pre-existing contract requirement.
[§21](../resource-model/v0alpha1.md#21-secrets) prohibits plaintext secrets in
resource declarations; [§22](../resource-model/v0alpha1.md#22-state-and-execution-journal) and
[§23](../resource-model/v0alpha1.md#23-compiler-pipeline) concern eventual
journal/compiler behavior, not present execution authority.
[§31](../resource-model/v0alpha1.md#31-mvp-execution-strategy) puts a fake process
before real adapters; [§33](../resource-model/v0alpha1.md#33-open-design-questions)
leaves further runtime decisions open.
[§32](../resource-model/v0alpha1.md#32-architectural-acceptance-tests) MVP acceptance
examples are not evidence that runtime safety is implemented in M2.

[ADR-0009](0009-m2-dependency-lifecycle-boundaries.md) separates logical graphs,
lifecycle and operations. [ADR-0013](0013-provider-instance-schema.md) and
[ADR-0014](0014-provider-binding-declarations.md) describe Provider/Binding data;
[ADR-0015](0015-offline-capability-phase-analysis.md),
[ADR-0016](0016-offline-provider-resolution.md) and
[ADR-0017](0017-explain-cli.md) retain explicit, offline queries.
[ADR-0018](0018-provider-configuration-secret-boundary.md) and
[ADR-0019](0019-m3-operation-context.md) are merged **Proposed** designs, not
implemented protections. Their status is unchanged here.

Current evidence, not a claim of runtime support:

| Symbol / source | Existing guarantee / relevant limitation |
| --- | --- |
| [ResourceIndex](../../src/diatonic/compiler/references.py) | Read-only identity mapping returned by the resolver; contained resource models remain mutable. Not an executable snapshot. |
| [NormalizedIR / normalize_resources](../../src/diatonic/compiler/normalize.py) | Detached full-fidelity snapshots and deterministic exports, including opaque Provider config. Not redacted or suitable for whole-model process handoff. |
| [PhaseRequest / DriverSupportMetadata](../../src/diatonic/compiler/capabilities.py) | Explicit phase query and caller-supplied support assertions. Neither authorizes execution nor admits installed code. |
| [ValidatedProviderBindings](../../src/diatonic/compiler/provider_bindings.py) | Exact Provider targets and immutable declaration summaries; configuration links are not infrastructure edges. |
| [ProviderResolution / resolve_phase_provider](../../src/diatonic/compiler/provider_resolution.py) | Deterministic offline selection/trace, not credential validation, actual-driver trust or dispatch authority. |
| [validate / graph / explain](../../src/diatonic/cli.py) | Offline pipelines; no provider launch, secret materialization or runtime command. |

Relevant existing evidence is in
[test_capabilities.py](../../tests/test_capabilities.py),
[test_provider_binding.py](../../tests/test_provider_binding.py),
[test_provider_resolution.py](../../tests/test_provider_resolution.py),
[test_normalized_ir.py](../../tests/test_normalized_ir.py) and
[test_cli_explain.py](../../tests/test_cli_explain.py). In particular,
`test_support_inspection_requires_supplied_metadata_not_provider_declarations`,
`test_configuration_link_is_not_a_graph_edge_or_stage_assignment`,
`test_configuration_is_never_inspected_even_on_errors` and
`test_no_files_written_no_executable_config_or_environment_discovery` protect
existing boundaries, not the proposed protocol. No executable provider protocol,
fake provider, runtime admission/authorization, secret backend or journal exists.

## 2. Glossary and invariants

| Term | Meaning |
| --- | --- |
| Phase | Resource lifecycle coordinate: `observe`, `provision`, `configure`. |
| Verb | Independently requested provider operation: `validate`, `observe`, `plan`, `apply`, `destroy`. A phase does not derive a verb. |
| Capability | Documented managed-phase demand, such as `virtual_machine.observe`; not verb support or permission. |
| Driver | An admitted executable implementation/version; its string ID alone proves nothing. |
| Provider instance | Exact logical `Provider/name`; two instances sharing a driver remain distinct. |
| Intent | ADR-0019's explicit authenticated single-resource/phase/verb request; not itself authorization. |
| Context | Proposed owned immutable snapshot binding that request to selection, policy, instance and admitted implementation. |
| Permit | Proposed host-internal single-use, scope-bound dispatch authority; never sent on the wire. |
| Invocation | One concrete attempt with a fresh host-generated ID and one short-lived child. |
| Result | A correlated, validated terminal reply, finalized only after clean IO closure and exit. |
| Diagnostic | A host-generated bounded code/projection, never raw child text or a traceback. |

All requirements in sections 3–11 are **proposed implementation requirements**.
The flow is:

```text
M1/M2 offline compilation
  -> explicit authenticated OperationIntent
  -> owned immutable OperationContext
  -> trusted authorization, effects/config preflight and scoped permit
  -> protocol gateway
  -> admitted synthetic fake process
  -> validated result or safe failure projection
```

There is no reverse dependency from compilation to the gateway. The gateway must
not parse YAML, select another Provider, infer operations from desired state or
Stage order, reopen `ResourceIndex`, read/export `NormalizedIR`, interpret M2
support JSON as authority, materialize references, expand shell expressions or
retry implicitly. Caller identity, actual admission evidence and permit remain
host-side. Echoing a context ID is correlation, never authentication.

## 3. Wire choice and experimental compatibility

| Alternative | Decision and tradeoff |
| --- | --- |
| JSON Lines / NDJSON over private stdin/stdout pipes | **Select.** A bounded LF-delimited frame is easy to produce in Python/Rust/Go; strict validation and a tiny envelope suffice for one attempt. Requires incremental byte limits and forbids pretty-printed wire frames. |
| JSON-RPC 2.0 | Do not select initially. It supplies RPC request/response/error conventions but is transport-agnostic; framing, byte ceilings and process lifecycle would still need this design. Notifications, batches and general methods add unnecessary scope for one fixed synthetic action. |
| Custom length-prefixed framed JSON | Do not select initially. Length headers permit multiline JSON, but add header parsing/length consistency and more cross-language framing cases without benefiting these small messages. |

See the [JSON-RPC specification](https://www.jsonrpc.org/specification) for the
comparison. We borrow no implicit JSON-RPC methods, notifications or retry rules.

Every message uses namespace/version `iac-provider/v0alpha1` and the exact
experimental profile `synthetic-one-shot-v1`. This is a **private experimental
wire layout for approved fake tests**, not a frozen public provider ecosystem.
The namespace and `iac/v0alpha1` resource API remain unchanged.

The core offers one exact protocol/profile in `hello`; `ready` acknowledges that
same pair. No downgrade, highest-common-version algorithm, version ranges or
fallback process. Unsupported namespace/profile fails negotiation. A different
experimental layout needs independent review, a new profile ID and bilateral
pinning; no silent acceptance of additional fields under this profile. Public
stabilization and any future protocol-version/API changes need separate review
and compatibility fixtures. Process advertisement cannot establish admission.

## 4. Framing, JSON validation and ceilings

Use RFC 8259 JSON with a stricter profile. [RFC 8259](https://www.rfc-editor.org/rfc/rfc8259)
is the underlying JSON reference; the additional limits here are ADR choices.

- A frame is one UTF-8 JSON object followed by exactly one LF byte (`0x0A`).
  Writers flush each complete frame. No BOM, CR/CRLF, blank line, comment, prefix,
  prompt, banner, leading/trailing non-JSON text or batch array. Horizontal JSON
  whitespace is accepted; key order is irrelevant. Canonical key sorting is not
  a signature or a wire requirement. An escaped newline is not a frame delimiter.
- Bound raw bytes **before decode or allocation of a complete JSON tree**. Decode
  strictly; reject invalid UTF-8. Decoded keys/strings in this first profile must
  be printable ASCII (`U+0020`–`U+007E`); reject controls and unpaired surrogates,
  including escaped forms. Non-ASCII resource names remain valid M2 data but are
  outside this synthetic profile and reject before launch, without schema change.
- Reject duplicate decoded object keys at every depth, including differently
  escaped spellings of the same key. Reject NaN/Infinity, overflow-to-infinity,
  every numeric value, `null`, and any type not allowed by the exact message schema.
  No implicit coercion. Only the result's literal boolean `false` is permitted;
  no field in this profile accepts `true` or arbitrary JSON values.
- Every object has an exact key set; all fields below are mandatory unless
  expressly stated otherwise (**none is optional in v1**). Unknown fields reject,
  including `config`, `secret_ref`, `outputs` and free-form `message`/`details`.
- Enforce nesting depth and collection budgets while scanning/decoding, not by
  checking after unlimited recursive parsing. A parser recursion failure becomes
  a safe protocol error; it must not escape as a value-bearing traceback.

| Budget | Proposed fixed ceiling / boundary |
| --- | --- |
| Frame bytes | 16,384 bytes before LF; the LF adds one byte. Reject at the first excess byte, even without a newline. |
| Frames per direction | Core: exactly `hello`, then at most one `invoke`. Child: exactly `ready`, then one terminal frame, or one early `reject` instead of `ready`. No progress/event/heartbeat frames. |
| Lifetime bytes per stdin or stdout stream | 32,770 bytes (two maximum frames with LFs); count all bytes, including garbage. Smaller per-frame and state-specific ceilings still apply. |
| Stderr | 4,096 bytes total; read/count/discard, never display or persist. The first excess byte aborts. Any amount below the limit is still untrusted, not a diagnostic channel. |
| Read chunks / owned byte buffering | Read at most 4,096 bytes per read; one 16,384-byte frame buffer plus one chunk per stdout reader. No accumulated stderr buffer. Transport/OS buffers are additional, not proof of a whole-process memory cap. |
| Decoded JSON complexity | Depth at most 6 (root counts as 1); at most 256 value nodes, 8 members/object, 8 items/array, 128 decoded bytes/string, 32 bytes/key. Per-field tighter limits below take precedence. |
| Concurrency | One invocation at a time per gateway instance; one child per invocation. No multiplexing or connection pool. |

After the terminal frame, **any additional stdout byte**, even whitespace or a
repeated correct reply, is an error. After `ready`, a second frame buffered before
`invoke` is unexpected. The child accepts only `hello` then `invoke` followed by
stdin EOF; extra input bytes reject. EOF with an unfinished frame is truncated;
EOF with no required next frame is premature. EOF after a valid final LF is not
alone success: process and both output pipes must also finish cleanly (§7).
Limits are hard profile ceilings. A host may tighten them and fail closed; a child
cannot negotiate them upward. Raising them requires a reviewed profile revision,
not an unbounded debug setting. No resynchronization after malformed input.

Syntax errors, BOM/CR framing violations and non-JSON constants map to
`invalid_json`; invalid UTF-8 maps to `invalid_utf8`; repeated decoded keys to
`duplicate_key`; structural budget violations to `complexity_exceeded`. Valid JSON
with forbidden primitives, wrong/missing/unknown fields or non-ASCII values maps
to `invalid_message`. Numbers are rejected as tokens without converting large
integers/floats. Valid but different correlation handles map to
`correlation_mismatch`; a valid message in the wrong state to `unexpected_message`.
After a terminal, extra bytes map to `extra_output`, subject to the byte-ceiling
precedence in section 7.

## 5. Exact messages and complete fictional examples

### 5.1 Shared envelope, identities and operation scope

All six types have exactly seven keys:

| Field | Type / validation |
| --- | --- |
| `protocol` | String, exactly `iac-provider/v0alpha1`. |
| `profile` | String, exactly `synthetic-one-shot-v1`. |
| `type` | String: `hello`, `ready`, `invoke`, `result`, `error`, `reject`; direction/state restrictions below. |
| `request_id` | Host-generated token for the logical authorized intent; grammar `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`. Not an idempotency or authorization key. |
| `invocation_id` | Fresh host-generated token of the same grammar for each attempt; no reuse during the gateway lifetime. |
| `context_id` | Same token grammar; opaque host handle for the exact frozen context, not a published hash of config/secrets or a serialized permit. |
| `payload` | Exact per-type object specified below; never arbitrary Provider data. |

The admitted fake fixture supplies the expected synthetic resource/Provider IDs.
Operation objects contain exactly `resource`, `provider`, `phase`, `verb`,
`capability`. Identities use canonical case-sensitive `Kind/name`, 1–128 printable
ASCII bytes and the existing nonempty slash/whitespace-free segment rules. The
resource must be a VM in the harness's explicitly admitted synthetic fixture set;
Provider must be the exact selected `Provider/name` in that fixture, never inferred
from a driver string. Do not copy labels, annotations, sources, references or specs.

Phase vocabulary is the three M2 phases; verb vocabulary is the five §13 verbs.
**Only** `(observe, observe, virtual_machine.observe)` is admitted by this profile.
Other pairs, mutation/simulation verbs and unsupported kinds reject host-side
before launch. The first fake experiment deliberately does not implement even
simulated plan/apply/destroy. Extending this set needs separate effect/permit and
profile review; a child advertising more operations cannot extend its authority.

`driver` objects have exactly `id`, `version`, `contract`, all strict ASCII
single-segment identifiers (no whitespace/slash), 1–64 bytes. They must exactly
match the trusted admitted fixture record; the examples use `mock.virtualization`,
`0.1.0-synthetic`, `synthetic-observe-1`. The executable path/artifact and expected
contract are approved before launch, not learned from this object. No vendor
branch or runtime registry is added to core.

### 5.2 Core offer: hello

Payload has exactly `driver`. The core has already validated a fake-only context
and permit for this restricted launch. Example (complete JSON; examples are
pretty-printed for reading, but **wire writers emit compact single-line JSON + LF**):

```json
{
  "protocol": "iac-provider/v0alpha1",
  "profile": "synthetic-one-shot-v1",
  "type": "hello",
  "request_id": "request-demo-1",
  "invocation_id": "attempt-demo-1",
  "context_id": "context-demo-1",
  "payload": {
    "driver": {"id": "mock.virtualization", "version": "0.1.0-synthetic", "contract": "synthetic-observe-1"}
  }
}
```

### 5.3 Child acknowledgement and untrusted advertisement: ready

Payload has exactly `driver`, `operations`. Driver echoes the admitted identity;
operations is a one-item array containing exactly the approved phase/verb/capability
triple. Each item has exactly those three keys. Ready must match the host's
pre-admitted contract, not authorize itself or change the frozen Provider instance.

```json
{
  "protocol": "iac-provider/v0alpha1",
  "profile": "synthetic-one-shot-v1",
  "type": "ready",
  "request_id": "request-demo-1",
  "invocation_id": "attempt-demo-1",
  "context_id": "context-demo-1",
  "payload": {
    "driver": {"id": "mock.virtualization", "version": "0.1.0-synthetic", "contract": "synthetic-observe-1"},
    "operations": [{"phase": "observe", "verb": "observe", "capability": "virtual_machine.observe"}]
  }
}
```

### 5.4 Core approved invocation: invoke

Payload has exactly `operation`, `synthetic`. The synthetic object has exactly
`case`, an enum `ok` or `reject`, explicitly chosen by the trusted harness, never
from resource config. This is the entire allowlisted nonsecret request. The host
rechecks/consumes the one-attempt permit immediately before writing any invoke
byte, then closes stdin after the full frame is drained. The child waits for this
frame **and stdin EOF** before its synthetic action.

```json
{
  "protocol": "iac-provider/v0alpha1",
  "profile": "synthetic-one-shot-v1",
  "type": "invoke",
  "request_id": "request-demo-1",
  "invocation_id": "attempt-demo-1",
  "context_id": "context-demo-1",
  "payload": {
    "operation": {"resource": "VirtualMachine/demo", "provider": "Provider/synthetic", "phase": "observe", "verb": "observe", "capability": "virtual_machine.observe"},
    "synthetic": {"case": "ok"}
  }
}
```

### 5.5 Synthetic result

Payload has exactly `operation`, `outcome`, `changed`. Operation must echo every
approved field exactly; outcome is exactly `synthetic_no_change`, changed is the
JSON boolean `false`. Only an `ok` case can return this result. No arbitrary outputs,
external IDs, messages or partial results. Successful decoding is provisional
until clean exit/EOF; no success is published early.

```json
{
  "protocol": "iac-provider/v0alpha1",
  "profile": "synthetic-one-shot-v1",
  "type": "result",
  "request_id": "request-demo-1",
  "invocation_id": "attempt-demo-1",
  "context_id": "context-demo-1",
  "payload": {
    "operation": {"resource": "VirtualMachine/demo", "provider": "Provider/synthetic", "phase": "observe", "verb": "observe", "capability": "virtual_machine.observe"},
    "outcome": "synthetic_no_change",
    "changed": false
  }
}
```

### 5.6 Structured provider rejection: error

For an invocation with synthetic case `reject`, payload has exactly `operation`
and `code`, with exact operation echo and code `synthetic_rejected`. This is a
provider-declared synthetic rejection, not a protocol parse failure. It is accepted
only with the same clean finish as a result, and only for that admitted inert case.

```json
{
  "protocol": "iac-provider/v0alpha1",
  "profile": "synthetic-one-shot-v1",
  "type": "error",
  "request_id": "request-demo-1",
  "invocation_id": "attempt-demo-1",
  "context_id": "context-demo-1",
  "payload": {
    "operation": {"resource": "VirtualMachine/demo", "provider": "Provider/synthetic", "phase": "observe", "verb": "observe", "capability": "virtual_machine.observe"},
    "code": "synthetic_rejected"
  }
}
```

### 5.7 Protocol rejection: reject

Payload has exactly `code`: `unsupported_version`, `unsupported_profile`,
`invalid_message`, `unsupported_operation`, or `unexpected_message`. No free-form
error text or offending value. This is an alternative terminal frame, never a
follow-up to result/error. Before ready, only the first three codes are permitted;
after invoke, only the last three. Receiving a reject never causes fallback.

```json
{
  "protocol": "iac-provider/v0alpha1",
  "profile": "synthetic-one-shot-v1",
  "type": "reject",
  "request_id": "request-demo-1",
  "invocation_id": "attempt-demo-1",
  "context_id": "context-demo-1",
  "payload": {"code": "unsupported_version"}
}
```

This example belongs to a negative negotiation case, not the successful hello
above. If generic bounded JSON reveals a different offered protocol/profile but
valid shared correlation tokens, a child implementing this profile may return one
reject in its own supported protocol/profile without interpreting the unknown
payload. Otherwise it closes without a reply. A gateway receiving an unknown
protocol/profile fails locally; it does not decode an unknown payload schema or
negotiate down. On locally detected malformed child output the gateway closes and
cleans up; it does not send a diagnostic frame that might echo untrusted data.

## 6. Process model, launch and isolation

Choose **one request per short-lived process**, no persistent sessions, pooling,
unsolicited startup hello, multiplexing, streaming results or callbacks. Startup
cost is acceptable for a fake experiment; clean EOF and attempt ownership make
fault/replay tests small. Persistent sessions would need separate cancellation,
credential-lifetime, fairness and cross-invocation isolation design.

The first gateway implementation target is **Linux/POSIX only**. A trusted test
harness pins an immutable admission record: absolute executable/interpreter/script
paths, fixed argv tuple, artifact identity/version, expected protocol/profile,
contract/triple, synthetic fixture IDs and fake-only permissions. No PATH search,
entry-point imports, YAML commands, executable discovery or user argument templates.
A file digest checks identity but does not itself confer trust. Files/interpreters
must live in a harness-controlled read-only location; mutable/untrusted admission
fails before launch. Bind the record to the exact Provider instance and context.

For a future Python 3.12 core use direct
[`asyncio.create_subprocess_exec`](https://docs.python.org/3.12/library/asyncio-subprocess.html),
not a shell. Native fixture argv is its admitted absolute binary path; a Python
fixture uses its admitted absolute interpreter, `-I`, and admitted absolute script
path. These are fixed harness tuples, not strings constructed from user values.
Use private PIPEs for stdin/stdout/stderr, `close_fds=True`, `pass_fds=()`, and a
new POSIX session/process group (`start_new_session=True`). Core alone writes
stdin and reads both output pipes concurrently. Stdout is exclusively protocol;
stderr bytes are counted/discarded privately. Set a StreamReader limit as an
additional bound, not the application frame ceiling. Avoid `communicate()` for
unbounded accumulation and blocking wait-without-draining patterns.

Use a fresh private mode-0700 working directory, no resource/config files there,
no request/output temporary files. Environment is exactly harness-approved
`LANG=C.UTF-8`, `LC_ALL=C.UTF-8`, `TMPDIR` pointing to that directory; no inherited
HOME, PATH, credentials, proxies or PYTHONPATH. Locale support is pinned by the
harness. Remove the private directory at completion; failure is not silent success.
No runtime result or journal persistence.

The harness must independently provide verified no-network containment, an
unprivileged user without infrastructure permissions, no host credentials or
sensitive mounts, read-only fixture files and only the private directory writable.
Initial external containment ceilings: 256 MiB memory, one CPU worth of quota,
at most 32 tasks (including language-runtime threads); the fixture contract
forbids spawning descendants. One fake child is expected. This admits ordinary
Python/Rust/Go runtimes without designing a plugin platform. Missing required
containment is an admission failure, not a silent unrestricted fallback. The
specific harness/container setup needs implementation review before any launch.

A subprocess and process group are **not a sandbox**. Group termination alone
cannot control code that escapes the group; the separately verified containment
and trusted fixture code remain necessary. These proposals do not protect against
a privileged host or guarantee secret erasure. Windows Job Objects, other OSes,
real provider privileges and real-secret transport are deferred; never pretend
POSIX kill semantics are portable. The wire format remains language-neutral.

## 7. State machine, deadlines and cleanup

All phases use a monotonic clock. Time zero `T0` is before attempting process
creation. No wait resets the absolute deadlines when partial data arrives.

| State | Required event / next state | Rejection/termination behavior |
| --- | --- | --- |
| `PREFLIGHT` | Receive owned context, admitted fixture, fake-only authority and unspent permit; validate all input/size/scope constraints → `STARTING`. | Invalid/missing evidence, wrong phase/verb or unavailable containment: reject before launch. No child or backend lookup. |
| `STARTING` | Launch pinned child, attach concurrent bounded readers and send/drain hello → `HELLO_SENT`. | Launch error or no completed handshake by `T0+2s`: latch failure and clean up any created child. |
| `HELLO_SENT` | One valid correlated ready, exact admitted driver/version/contract and operation tuple → `READY`. | Reject, wrong identity/version/profile/support, malformed data, EOF, nonzero exit or any unexpected type → failure. No invoke is written. |
| `READY` | Recheck exact context and permit, consume permit, send/drain invoke and close stdin → `REQUEST_SENT`. | Revocation/mismatch/cancellation: abort. Any premature terminal/extra stdout before dispatch: protocol failure. |
| `REQUEST_SENT` | One complete correlated result/error, or permitted reject → `TERMINAL_PENDING`. | Wrong operation/IDs, malformed/truncated/oversized/extra output, exit/EOF without a terminal or deadline: abort, do not publish partial result. |
| `TERMINAL_PENDING` | Zero exit status, stdout EOF with no extra byte, stderr EOF within budget, all validation and directory/handle cleanup succeed → final outcome. | Nonzero/signal exit even after valid result, extra/replayed frame, flood, lingering handles, cancellation or deadline invalidates pending success. |
| `ABORTING` | Close stdin; bounded termination, reap, close readers/handles and remove directory → failure outcome. | Never resume parsing, restart process or retry implicitly. Cleanup failure remains visible and suppresses success. |

A second core invoke is forbidden. On normal terminal acceptance, no shutdown
message is sent: stdin is already closed and the child must close its streams and
exit 0. Core success requires both EOFs **and** reaping the exact child. Zero exit
without a required frame is not success. An early reject also needs clean finish.

| Deadline/budget | Proposed value |
| --- | --- |
| Launch + hello + validated ready | By `T0+2s`, including hello write/drain. |
| Invoke write/drain + terminal frame | By `min(ready_time+3s, T0+5s)`. No separate unbounded stdin drain. |
| Terminal finish (exit + both EOFs) | By `min(terminal_time+1s, T0+6s)`. Early negotiation reject uses this finish budget too. |
| Entire active attempt | Hard application deadline `T0+6s`, regardless of partial frames. |
| Abort escalation | SIGTERM to group; wait at most 0.5s; SIGKILL if needed; reap/drain/close at most another 1s; directory cleanup at most 0.5s. Total cleanup budget 2s. |

Cancellation is out-of-band host cancellation, not a new wire message. Check it
before invoke and before final publication; once observed, latch it and abort.
Readers must continue bounded draining/discarding during termination so a full
pipe cannot deadlock cleanup. At cleanup deadline close remaining handles and
report `cleanup_failed`; retain only a bounded host-internal reference to an
unreaped child for supervisor intervention, block further gateway launches, and
never report it reaped if it is not. Do not await indefinitely or silently detach.
Kernel/host failures can prevent timely kill/reap; the nominal 8s active+cleanup
budget is a testable application policy, not a hard OS scheduling guarantee.

Validation precedence within one received chunk is byte/framing ceilings, strict
UTF-8/JSON/complexity, exact envelope/version/profile, correlation/state, then
payload/admission/operation. Process events and cancellation enter one serialized
gateway event loop; the first observed violation latches. Cleanup failure overrides
the primary public code, retaining at most one safe cause code internally. Tests
fix event/clock order; different scheduling races may expose different first
failures. There is no claim of a globally deterministic ordering of physical IO
races. No later good message can turn a failed attempt into success.

## 8. Outcome, diagnostic and retry contract

Conceptual internal result: host-owned request/invocation/context handles, exact
approved operation and Provider/driver references, `mode=synthetic`, final outcome,
`changed` (`false` only for verified inert success/rejection, otherwise unknown),
and one safe diagnostic or none. It retains no arbitrary provider outputs. This
is not a wire schema or a persistent journal. Resource Model §14's richer result
is illustrative; it does not require accepting external IDs/outputs from this fake.

| Final outcome | Meaning / qualification |
| --- | --- |
| `rejected_before_dispatch` | Invalid input/authority before any invoke byte is written; no approved operation was dispatched. If a child was launched, this does not prove its startup had no effects. |
| `negotiation_failed` | Ready/handshake mismatch or early reject; no invoke byte sent. Child startup is still not a general no-effects guarantee. |
| `synthetic_success` | Exact allowed result, clean finish and cleanup; `changed=false` describes only the admitted inert fake contract. |
| `provider_error` | Exact `synthetic_rejected` error, matching reject test case and clean finish; no arbitrary exception text. |
| `protocol_rejected` | Valid correlated reject after invoke and clean finish. This says the peer rejected the exchange, not that a general real operation had no effects; changed remains unknown. |
| `indeterminate` | Invoke may have been delivered and no trustworthy complete outcome survived validation/finish, including crash, timeout, cancellation or nonzero exit after a result. Never assume unchanged or roll back automatically. |

The gateway marks possible dispatch **before writing the first invoke byte**;
partial writes, missing LF or failed drain cannot justify a no-effects claim.
Without dispatch, protocol/IO failures are negotiation failures; input revocation
at READY is rejected-before-dispatch. Cleanup failure is a diagnostic overriding
any pending success; after possible dispatch, outcome becomes indeterminate.

Stable proposed local diagnostic codes (not existing M2 codes):

| Category | Codes |
| --- | --- |
| Host input/admission | `invalid_gateway_input`, `admission_denied`, `context_mismatch`, `launch_failed` |
| Negotiation | `unsupported_version`, `unsupported_profile`, `driver_mismatch`, `operation_mismatch`, `peer_protocol_rejected` |
| Framing/schema | `frame_too_large`, `stdout_budget_exceeded`, `invalid_utf8`, `invalid_json`, `duplicate_key`, `complexity_exceeded`, `invalid_message`, `truncated_frame`, `premature_eof` |
| Sequence/correlation | `unexpected_message`, `correlation_mismatch`, `extra_output` |
| Process/lifetime | `stderr_budget_exceeded`, `process_exit_nonzero`, `process_terminated`, `deadline_exceeded`, `cancelled`, `cleanup_failed` |
| Admitted fake error | `synthetic_rejected` |

An internal event holds only enum code/state, byte counts, validated host handles,
exit status/signal and at most one bounded cause code. Raw frame/decoder input,
stderr, argv/env, Provider config, secret references, exception repr/locals and
unclassified outputs must never enter that record. Drop transient byte buffers
on failure. Python/OS copies can remain; this is not a zeroization guarantee.

The public projection is smaller: code, stage enum, host-generated request and
invocation handles (subject to recipient policy), and fixed text from a host
catalog. Copy no peer free text, driver-advertised values, invalid field names,
paths, raw bytes or exception message. A field path may be emitted only as a known
schema-path enum, not an arbitrary key. No raw output passthrough even in debug
mode or CI. Internal events are restricted, not automatically public telemetry;
future journal/export paths need ADR-0018's separately reviewed projection.

Request ID identifies intent; invocation ID identifies attempt. New attempts need
fresh explicit authority, a new permit and invocation ID. Response IDs must equal
the exact pending tuple, with operation fields also equal; old/duplicate/late
messages fail or are discarded after terminal teardown, never applied to another
attempt. Neither a correlation token, context hash nor deterministic reply proves
idempotency or exactly-once execution. No automatic retries, including after
ambiguous real mutations; real retries require separate observation/reconciliation
and effect-specific design. This profile authorizes no real mutation at all.

## 9. Threat model and consequences

| Threat / misuse | Proposed mitigation / limit |
| --- | --- |
| YAML or support JSON treated as runnable authority | Gateway accepts only the approved host context/permit and fixture admission; no compiler-to-runtime shortcut. |
| Child self-advertises a more privileged driver/operation | Compare exact pre-admitted identity/contract/triple; advertisement never grants authority. |
| Same-driver/different-Provider or stale-context replay | Exact instance/context and attempt binding, immutable inputs and final permit recheck; no reselection. |
| Huge/deep/duplicate/invalid JSON or stdout/stderr flood | Pre-decode byte and structural caps, strict keys/types, continuous bounded draining and abort. No resynchronization. |
| Secrets or malicious markup in process error output | No value passthrough; raw output tainted even for synthetic tests; only enum projections. Keyword scrubbing is insufficient. |
| Valid result followed by crash/extra output | Delay publication until zero exit, both EOFs, validation and cleanup. Failure is not overwritten by a pending result. |
| Hanging child or descendant retaining pipe | Monotonic deadlines, POSIX group escalation, bounded cleanup and supervised unreaped-child failure. No sandbox claim. |
| Unknown side effects or cancellation race | Indeterminate outcome after possible dispatch; no implied rollback, no retry or unchanged claim. |

Costs: process startup per request, intentionally narrow ASCII/synthetic data,
strict version/profile matching and more rejections. Benefits: small cross-language
state machine, bounded exposure and explicit responsibility boundaries. OS-level
malice, kernel failure, malicious admitted code and real infrastructure safety are
not solved by JSON framing, pipes, hashes or this ADR. M2 remains offline and
full-fidelity IR remains potentially sensitive; no namespace or public YAML change.

## 10. Proposed verification and implementation sequencing

These are **future acceptance tests**, not tests or executable skeletons added now:

1. Pure immutable message/schema and deterministic state-machine tests first,
   using byte chunks and a fake clock, with no subprocess. Verify no permit is
   consumed twice, no mutable index access and no inferred operations.
2. A separately reviewed minimal Linux one-shot gateway plus synthetic fixture,
   admitted explicitly by the harness, for exact hello/ready/invoke/result/error
   and clean EOF/exit. Test empty stderr and bounded harmless stderr alike.
3. Pinned fault fixtures for crashes, hangs, malformed/flood output and retained
   pipes, not arbitrary executable paths or commands supplied through YAML/argv.
   Run only after containment and audit/design gates are approved.

Positive and negative cases must include:

- Golden UTF-8 JSONL vectors shared with later Python/Rust/Go implementations;
  object-order permutations accepted; all field types/requiredness exact; compact
  writers and partial pipe reads/writes interoperable. No cross-language provider
  implementation is required by this documentation PR.
- Every supported exchange, synthetic reject, protocol reject and identity/tuple
  echo. Wrong namespace/profile, actual driver/version/contract, extra advertised
  operation, wrong capability/phase/verb, wrong Provider/resource and stale permit
  stop before invoke whenever detectable there.
- Duplicate keys at every level, escaped duplicate keys, invalid UTF-8/BOM/CRLF,
  blank lines, multiline frames, truncated/empty EOF, trailing garbage, numeric
  values/NaN/Infinity, escaped controls/surrogates, missing/unknown keys and wrong
  containers. Test depth 6/7, frame 16,384/16,385, stderr 4,096/4,097 and stream
  lifetime ceilings; rejection must precede unbounded tree construction/reads.
- Result before ready/invoke, second ready, duplicate/replayed/late result, wrong
  correlation token and extra byte after terminal; correct result followed by
  signal/nonzero exit must never publish success.
- Handshake/write/response/finish deadline edges, zero-progress partial frames,
  stdout/stderr flooding concurrently, timeout/cancellation before and after
  first invoke byte, crash before response, and startup/process-creation failure.
- Descendant-held pipes, kill/reap/handle/directory cleanup failures and exact
  escalation budgets; no hidden retry, hanging await or false reaped status.
- Synthetic public sentinel echoes in stdout/stderr/exception text must not reach
  public diagnostics, artifacts or future journals. Do not use real credentials.
- Minimal argv/env/descriptors, private cwd cleanup, network denied by containment,
  no host credentials/mounts, no real endpoints/adapters/operations and no secret
  lookup. No Provider config, reference values, full IR or unrelated resources
  cross the process boundary. Containment absence rejects admission.
- Full M1/M2 regressions and byte-compatible validate/graph/explain/IR behavior.

For this ADR only: validate Markdown spans/fences/tables, all six JSON examples,
relative links/section anchors, implementation symbols and absence of credentials
or private endpoints; run existing sync, Ruff, pytest and diff checks if available.
Those checks verify documentation and current regressions, not the future gateway.

## 11. Deferred work and implementation gates

| Gate | Required evidence / disposition | Does not authorize |
| --- | --- | --- |
| This design review | Independent review of exact profile/messages, limits, launch/isolation assumptions and failure semantics. ADR remains Proposed until human disposition. | Running any provider or changing ADR-0018/0019 status. |
| Synthetic fake-process implementation | Explicit disposition of open audit #38; human review/acceptance of ADR-0018/0019 proposals and ADR-0020; narrow implementation issue/PR scope; approved fake-only admission/permit boundary, Linux containment and negative-test plan before launching a child. | Real credentials, arbitrary executable discovery, persistent sessions, real provider operations or a runtime CLI. |
| Real-secret transport or real adapters | Separately reviewed trusted contracts/admission, operation authorization/effect policy, late secret scope, redacted projections, host security, freshness, failure/reconciliation and destructive dispatch safeguards with tests. A new appropriate wire profile/compatibility review is required. | Treating static support or this fake profile as installed readiness or authorization. |

Priority follow-ups, **proposals only; no Issues created**: first agree the bounded
message/state-machine fixtures and fake-only admission/permit interface; then
approve a concrete Linux containment/test-harness implementation; then review the
small synthetic gateway/fixture increment. Protocol stabilization, Windows/other
platform containment, persistent sessions, generalized operations/config/output
schemas, discovery, generated secret outputs, retry/idempotency contracts, journal,
state and real adapters remain deferred. No `plan`, `apply`, `destroy`, scheduler,
secret backend or provider executable is implemented or enabled by this ADR.
