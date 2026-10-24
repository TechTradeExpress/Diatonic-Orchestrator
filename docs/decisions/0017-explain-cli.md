# ADR-0017: Provider-free explain CLI and explicit offline phase queries

## Scope and authority

Resource Model v0.1 defines logical identities, dependencies, Stage declarations,
lifecycle ownership, capabilities and ProviderBindings. ADR-0011/0012 establish
immutable graph/Stage analyses; ADR-0014–0016 establish declaration validation,
explicit phase demand and conservative offline selection. Issue #36 authorizes a
CLI view over these APIs. This ADR freezes an internal human-readable CLI contract,
not a new Resource Model, versioned exporter or provider manifest protocol.

No normative model, namespace, graph, Stage, phase or selection algorithm changes.
The final planned M2 increment remains offline; execution belongs to separately
reviewed later milestones.

## Command and usage

```text
diatonic explain RESOURCE FILE [FILE ...] [--phase PHASE] [--support-metadata FILE]
```

RESOURCE is a required exact case-sensitive canonical `Kind/name`. One or more
explicit YAML paths are required; multi-document files and forward/cross-file
references use the existing loader/resolver. There is no directory discovery,
implicit configuration, environment variable or global metadata registry.

PHASE is one of `observe`, `provision`, `configure`. Missing positional arguments,
malformed RESOURCE syntax, unknown flags, invalid phases and support metadata
without a phase are usage errors (exit 2). A syntactically valid but undeclared
identity is `unknown_explain_resource` (exit 1); no fallback to another name/kind.

Example baseline, with explicit Stage fixtures:

```sh
uv run diatonic explain VirtualMachine/app01 examples/infrastructure/resources.yml tests/fixtures/reference-stages.yml
```

Baseline explanation requires no Provider, ProviderBinding or driver metadata.
Declaring a phase managed does not request its analysis. Output ends with
`Provider resolution: not requested` when `--phase` is absent.

## Composition and failure ordering

The command calls, in order:

1. `load_yaml_files(files)` and `resolve_resources(documents)`.
2. `validate_ipv4_semantics(index)` and `validate_provider_bindings(index)`.
3. `normalize_resources(index)` as a check; no artifact is written.
4. `classify_dependencies(index)`, `build_dependency_graph(index, facts)` and
   `analyze_stage_order(index, graph)`.
5. Verify the requested identity is present.
6. Only with `--phase`, construct `PhaseRequest`, call `analyze_phase_request`,
   optionally read local support metadata for managed ownership, and delegate to
   `resolve_phase_provider` using the validated binding summaries.
7. Format and print only after every requested pass succeeds.

Whole-input consistency matters even when a conflict is unrelated to the selected
resource. Dependency cycles fail before Stage analysis, with the existing closed
witness and every edge reason. Stage conflicts retain both assignments/orders,
directed dependency path, all reasons and document-root provenance. Unknown
resource lookup precedes phase analysis; unsupported managed pairs precede JSON
input loading. For managed requests, malformed supplied metadata fails before
selection; otherwise ADR-0016's selection diagnostic precedence is unchanged.

Existing `validate` and `graph` pipelines and text remain unchanged. They never
implicitly request phase analysis or require driver-support metadata.

## Baseline presentation

Output is plain text rendered with literal Rich `Text` and soft wrapping. There
are no width-dependent tables. Successful output contains no source filenames;
portable text depends on logical declarations and canonical analysis ordering.
Sections display:

- Exact identity; no spec, Provider configuration, extensions or secret dump.
- **Direct prerequisites** and **direct dependents**, with arrows consistently
  prerequisite → dependent. These are filtered existing graph edges, not a
  transitive closure. Every reason is preserved in graph order, including repeated
  declarations, explicit/implicit classification, owner and exact field path.
  Integer indexes remain numeric, including values above nine.
- Explicit Stage identity and numeric order from M2.3, or `unassigned`. A Stage
  declaration does not acquire its own rank. Position is 1-based in the exact
  M2.3 logical topological order, including all logical vertices. This is offline
  logical analysis, not runtime readiness or an apply/delete schedule.
- Declared lifecycle values, as described below.
- Optional phase and Provider-resolution sections, or the explicit not-requested
  message. Empty edge/candidate sections use `(none)`.

Names and error paths containing Rich markup characters are rendered literally.
No source path or terminal width determines successful ordering. Help and usage
messages remain conventional Typer presentation.

## Lifecycle omission and null

Use the existing Pydantic `model_fields_set`, not lifecycle defaults. The display
includes `lifecycle`, `lifecycle.phases`, and all six requested leaf fields:
`stage`, `desired_state`, `prevent_destroy`, `phases.observe`, `phases.provision`,
`phases.configure`, each prefixed by `lifecycle.`.

An absent field is `(omitted)`, an explicitly null field is `null`, a declared
lifecycle/phases object is `declared`, and declared scalar values render directly
(with lowercase `true`/`false`). Children of absent/null parents are `(omitted)`;
the parent's own line retains the original absence/null distinction. Thus null
lifecycle, null phases, omitted individual phase and null individual phase remain
distinguishable without inventing ownership. No output interprets `absent` as a
destruction request or `prevent_destroy: false` as authorization.

## Explicit phase and Provider resolution

With `--phase`, show requested phase, ownership, declaration origin and documented
required capability or `(none)`. M2.7's origin labels distinguish all omission/null
cases. External ownership reports externally owned; disabled reports not applicable;
unspecified remains unspecified. All three have no managed demand or selection,
require no metadata, and **do not read** even an explicitly supplied metadata path.
The existing M2.8 nonmanaged result is used, rather than a second ownership policy.

A managed query delegates exact matching, priority and uncertainty decisions to
M2.8. Success shows selected Binding, Provider, driver ID and priority, prominently
qualified as **offline declared support only**. Every evaluated binding is shown
in the resolver's canonical order, with outcome, Provider, priority, capability,
driver/support status (or not inspected), and all reason codes/field paths and
available expected/actual selector values. Rejected candidates do not cause driver
lookup. Unknown lower-priority metadata remains visible without blocking a
confident unique winner.

Failure uses the exact existing M2.8 code, phase context and complete candidate
trace: no matches, all unsupported, decisive unknown metadata, ambiguity or invalid
input. Both successful selection and errors remain declaration-based facts, not
installation, authentication, endpoint availability or environment compatibility.

## CLI-only local support JSON

An explicit managed query can supply a UTF-8 JSON file:

```json
{
  "drivers": [
    {
      "driver_id": "example.driver",
      "capabilities": ["virtual_machine.provision"]
    }
  ]
}
```

For the repository's non-secret, non-executable example:

```sh
uv run diatonic explain VirtualMachine/app examples/offline-resolution/resources.yml --phase provision --support-metadata examples/offline-resolution/driver-support.json
```

The root must contain exactly the required `drivers` array. Every entry must
contain exactly required `driver_id` and `capabilities` array. Unknown keys,
missing keys, invalid containers and duplicate JSON keys at any depth fail. Numeric
values (including non-finite constants/overflow), booleans, nulls and objects are
not valid driver/capability strings. Standard-library JSON parsing uses strict
key/number hooks; identifier syntax, duplicate drivers/capabilities and canonical
ordering are delegated to M2.7 constructors.

`{"drivers": []}` is valid and means no supplied descriptors. An empty capabilities
array explicitly declares no supported capabilities for that driver. An omitted
file or missing descriptor stays unavailable, never declared unsupported or
inferred from driver names/configuration. Parsing never imports or executes any
content. This format is local, unversioned and specific to this CLI adapter, not
a YAML resource, driver discovery API, extensible configuration framework or
`iac-provider/v0alpha1` manifest/transport.

## Errors, streams and privacy

- Exit 0: complete requested analysis, stdout only.
- Exit 1: expected compiler/graph/Stage/phase/resolution/JSON error, stderr only;
  no traceback or successful partial explanation.
- Exit 2: conventional Typer usage error.

Existing error formatters are reused for M1 checks and graph/Stage witnesses.
Phase errors retain M2.7 diagnostics. Provider errors render stable code, requested
resource/phase/capability, every candidate's details/reasons and canonical sources.
Coordinates are explicitly document roots, never invented exact field locations.

Local adapter codes are `support_metadata_read_error`,
`support_metadata_decode_error`, and `invalid_support_metadata` for JSON syntax or
shape errors. M2.7's `invalid_driver_descriptor`, `duplicate_driver_descriptor`
and `duplicate_driver_capability` codes are retained for descriptor failures.
These messages give the path and generic actionable context; JSON syntax errors
also give actual parser line/column. They never echo file contents, invalid values
or operating-system exception payloads. Support JSON coordinates are parser
positions, distinct from resource document-root provenance.

The formatter never inspects Provider configuration or extensions. Selection
traces include only existing public identity/selector/support facts. No credentials
or secret references are loaded, interpolated or shown. Only expected exceptions
are handled; unrelated programming failures are not broadly hidden.

## Remaining boundaries

No driver installation/discovery/import, provider initialization, mock/real
execution, live state, operation classification, runtime phase scheduling, journal,
state persistence, plan/apply/destruction or machine exporter is introduced.
M2 completion means offline declarations and inspection are implemented and tested;
it does not imply the MVP's runtime safety or lifecycle semantics are complete.
