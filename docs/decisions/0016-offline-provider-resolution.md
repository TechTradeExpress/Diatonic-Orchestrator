# ADR-0016: Deterministic offline provider resolution

- Status: proposed for independent review with M2.8
- Scope: internal library analysis; no Resource Model or namespace changes
- Builds on: ADR-0009, ADR-0014 and ADR-0015

## Contract and boundary

The normative Resource Model separates lifecycle ownership, capabilities, logical
Provider instances, driver IDs and ProviderBinding declarations. M2.6 validates
binding schemas and exact Provider targets. M2.7 identifies capability demand for
one explicitly requested phase and independently inspects supplied driver support
metadata. This increment consumes those results; it does not infer phase requests.

The matching, priority, uncertainty and trace policies below are internal M2.8
choices submitted for review, not additions to the public YAML contract.

## API and immutable records

`diatonic.compiler.provider_resolution.resolve_phase_provider(index, analysis,
bindings=None, metadata=None) -> ProviderResolution` consumes a successful
`PhaseAnalysis` from `analyze_phase_request`. For example, given an index containing
a managed VM provision phase, `Provider/primary` using `example.driver`, and a
matching binding:

```python
analysis = analyze_phase_request(
    index, PhaseRequest("VirtualMachine/app", "provision")
)
bindings = validate_provider_bindings(index)
metadata = DriverSupportMetadata((
    DriverSupportDescriptor("example.driver", ("virtual_machine.provision",)),
))
result = resolve_phase_provider(index, analysis, bindings, metadata)
# result.fact.selection identifies the binding, Provider, driver and priority.
```

A managed request requires an explicit `ValidatedProviderBindings` result,
including an empty result when no bindings exist. `None` is invalid for managed
demand: callers must establish declaration validation rather than implicitly
skip it. Metadata may be omitted; this means no supplied descriptors, not absence
of capability support.

External, disabled and unspecified requests return those distinct statuses,
`selection=None` and an empty candidate tuple. They require neither bindings nor
metadata and do not inspect unused arguments. Desired state, prevent_destroy,
Stage order and dependencies never initiate resolution or imply operations.
Unsupported managed pairs remain M2.7 errors when constructing phase analysis.

`ProviderResolution.fact` contains the portable phase fact, status, optional
`ProviderSelection` and candidate tuple. Selection records identify binding,
Provider, opaque driver ID and declared priority. `sources` is separate and keyed
by resource identity. It covers the requested resource, all bindings and their
Provider targets. Positions are copied document-root coordinates, never claimed
as exact field locations. Source paths do not participate in matching or sorting.

Records are frozen/slotted; sequences are tuples and mappings are owned read-only
copies. No Pydantic resource, Provider configuration, executable object or mutable
caller container is retained. Completed results and diagnostics are detached from
subsequent model/input changes. This is an internal representation, not a new
versioned export format.

## Exact matching and priority

For each validated declaration, compare:

1. Exact capability equality with the explicit demand.
2. Exact case-sensitive resource kind equality.
3. Exact equality of every selector label; absent resource labels fail matching.

An empty selector-label mapping imposes no label constraint. There is no wildcard,
expression, selector specificity, extra scoring or fallback by names/driver IDs.
The existing M2.6 schema remains the selector grammar.

For structural matches, read only the exact Provider's driver ID and inspect
caller-supplied M2.7 support metadata. Do not inspect or retain `spec.config`.
Support is declared supported, declared unsupported or metadata unavailable.

The **highest numeric priority among declared-supported candidates wins** if
unique. Negative, zero and positive integers compare normally. Two top supported
bindings are ambiguous even when they point to the same Provider. Identity and
file ordering never break a tie. Lower-priority candidates remain visible.

## Uncertainty and diagnostic precedence

Missing metadata represents uncertainty. With a supported candidate at priority
50 and an unknown candidate at 100 or 50, selection is blocked. With a unique
supported candidate at 100 and an unknown candidate at 50, select the supported
candidate and preserve the unknown lower-priority trace.

The fail-fast decision order is:

1. `invalid_provider_resolution_input`: malformed or detectably incompatible inputs.
2. `no_matching_provider_binding`: no structural match, even without metadata.
3. `missing_driver_support_metadata`: an unknown match could affect the winner
   or top tie (no supported candidate, or unknown priority >= highest supported).
4. `no_supported_provider_binding`: structural matches exist and all are
   definitively unsupported.
5. `ambiguous_provider_binding`: multiple top supported candidates and no
   potentially decisive unknown metadata.
6. Successful unique selection.

Thus decisive unknown support takes precedence over an apparent supported tie.
Unknown candidates below a supported tie do not prevent the ambiguity diagnostic.
There is no successful partial result on failure. `ProviderResolutionError`
contains an immutable `ResolutionDiagnostic` with stable code, actionable message,
phase context, full candidate trace, relevant binding IDs and detached sources.
Input failures can precede evaluation and therefore have an empty trace. They
never include Provider config or secret values.

## Candidate traces and deterministic ordering

Evaluate every binding, sorted by case-sensitive canonical binding identity.
Structural mismatches collect all applicable reasons: capability, then kind,
then label keys in case-sensitive lexicographic order. Each reason includes its
exact tuple field path and, for selector comparisons, expected/actual strings.
Only structural matches inspect driver support; rejected candidates have no
driver/support assessment.

Outcomes are `rejected`, `metadata_unavailable`, `unsupported`, `outranked`,
`selected`, `ambiguous_highest_priority`, or `supported_unresolved`. The last
means a known top candidate is blocked by uncertainty, not definitively tied or
selected. Reasons distinguish support unavailable/unsupported, lower priority,
selection uncertainty, highest-priority tie and unique selection. Unknown lower
candidates retain their unavailable outcome plus a lower-priority reason.
Repeated distinct bindings never collapse, even with identical Provider targets.
Relevant error binding IDs and source mappings use canonical identity ordering.
No filename, declaration order or hash iteration order affects portable facts.

## Focused input consistency

The API expects matching successful M1–M2.7 inputs. It re-analyzes only the supplied
explicit phase request, comparing its fact and root provenance against the index.
It checks complete binding-summary coverage, duplicate summaries, primitive types,
field paths, current binding specs using the existing schema, typed Provider
identities and required root provenance. It validates matching Provider driver IDs
without traversing their configurations. Supplied support metadata is detached and
revalidated using the M2.7 constructors. Controlled input errors replace missing
lookup or malformed-summary failures.

This does not rebuild the reference resolver or binding validation pass, and is
not a general freshness framework. Earlier snapshots do not capture resource
labels or historical Provider driver IDs; valid changes to those fields before
resolution cannot be identified as stale. Callers must pass matching snapshots.
Changes after a completed resolution cannot alter that result. No hashes, state
or global compiler context are introduced to detect historical changes.

## Deferred behavior and M2.9

Declared support is not proof of driver installation, authentication, endpoint
availability, environment compatibility or execution readiness. There is no driver
discovery, vendor inference, secret lookup, interpolation, initialization,
execution, scheduling, state, planning or destruction.

M2.9 can compose an explicit phase request, capability analysis, supplied metadata
and this resolver to implement `diatonic explain`, rendering the existing facts
and diagnostics. M2.8 adds no CLI command and does not change `validate` or `graph`
pipelines, output, dependency edges or normalized IR. Binding declarations remain
valid even when a later explicit resolution query would be ambiguous or uncertain.
