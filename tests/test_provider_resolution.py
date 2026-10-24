"""Real-pipeline tests for offline selection, uncertainty, and immutable traces."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from diatonic.cli import app
from diatonic.compiler.capabilities import (
    DriverSupportDescriptor,
    DriverSupportMetadata,
    PhaseAnalysisError,
    PhaseRequest,
    analyze_phase_request,
)
from diatonic.compiler.dependencies import classify_dependencies
from diatonic.compiler.graph import build_dependency_graph
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.normalize import normalize_resources
from diatonic.compiler.provider_bindings import validate_provider_bindings
from diatonic.compiler.provider_resolution import (
    ProviderResolutionError,
    resolve_phase_provider,
)
from diatonic.compiler.references import resolve_resources
from diatonic.compiler.stages import analyze_stage_order
from diatonic.model.base import ResourceBase

CAPABILITY = "virtual_machine.provision"


def vm(name="app", ownership="managed", labels=None, **fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "VirtualMachine",
        "metadata": {
            "name": name,
            "labels": {"site": "lab", "role": "app"} if labels is None else labels,
        },
        "spec": {"cpu": {"cores": 1}, "memory": {"mib": 512}},
        "lifecycle": {"phases": {"provision": ownership}},
        **fields,
    }


def provider(name="primary", driver="example.driver", **fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Provider",
        "metadata": {"name": name},
        "spec": {"driver": driver, "config": {}},
        **fields,
    }


def binding(
    name="primary",
    target="primary",
    priority=100,
    capability=CAPABILITY,
    kind="VirtualMachine",
    labels=None,
    **fields,
):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "ProviderBinding",
        "metadata": {"name": name},
        "spec": {
            "capability": capability,
            "match": {"kind": kind, "labels": {} if labels is None else labels},
            "provider": f"Provider/{target}",
            "priority": priority,
        },
        **fields,
    }


def metadata(*driver_ids, unsupported=()):
    return DriverSupportMetadata(
        tuple(
            DriverSupportDescriptor(
                driver, () if driver in unsupported else (CAPABILITY,)
            )
            for driver in driver_ids
        )
    )


def write(tmp_path, documents, filename="input.yml"):
    path = tmp_path / filename
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8")
    return path


def pipeline(paths, identity="VirtualMachine/app", phase="provision"):
    index = resolve_resources(load_yaml_files(paths))
    declarations = validate_provider_bindings(index)
    analysis = analyze_phase_request(index, PhaseRequest(identity, phase))
    return index, analysis, declarations


def inputs(tmp_path, documents=None, **kwargs):
    path = write(
        tmp_path, [vm(), provider(), binding()] if documents is None else documents
    )
    return pipeline([path], **kwargs)


def failure(arguments, support, code):
    with pytest.raises(ProviderResolutionError) as caught:
        resolve_phase_provider(*arguments, support)
    assert caught.value.diagnostic.code == code
    assert all(
        candidate.outcome != "selected"
        for candidate in caught.value.diagnostic.candidates
    )
    return caught.value.diagnostic


def test_unique_managed_selection_has_explicit_demand_and_exact_logical_ids(tmp_path):
    args = inputs(tmp_path)
    result = resolve_phase_provider(*args, metadata("example.driver"))
    assert result.fact.status == "selected"
    assert result.fact.phase == args[1].fact
    assert result.fact.phase.request == PhaseRequest("VirtualMachine/app", "provision")
    assert result.fact.phase.required_capability == CAPABILITY
    selection = result.fact.selection
    assert (
        selection.binding_identity,
        selection.provider_identity,
        selection.driver_id,
        selection.priority,
    ) == ("ProviderBinding/primary", "Provider/primary", "example.driver", 100)
    trace = result.fact.candidates
    assert len(trace) == 1 and trace[0].outcome == "selected"
    assert trace[0].support_status == "declared_supported"
    assert [reason.code for reason in trace[0].reasons] == ["selected_highest_priority"]
    assert set(result.sources) == {
        "VirtualMachine/app",
        "ProviderBinding/primary",
        "Provider/primary",
    }


@pytest.mark.parametrize(
    "change,code",
    [
        ({"capability": "virtual_machine.configure"}, "capability_mismatch"),
        ({"capability": "Virtual_machine.provision"}, "capability_mismatch"),
        ({"kind": "virtualmachine"}, "kind_mismatch"),
        ({"kind": "FutureKind"}, "kind_mismatch"),
        ({"labels": {"missing": "value"}}, "missing_label"),
        ({"labels": {"site": "LAB"}}, "label_mismatch"),
        ({"labels": {"site": "lab", "role": "other"}}, "label_mismatch"),
    ],
)
def test_exact_matching_and_label_conjunction(tmp_path, change, code):
    args = inputs(tmp_path, [vm(), provider(), binding(**change)])
    diagnostic = failure(
        args, metadata("example.driver"), "no_matching_provider_binding"
    )
    candidate = diagnostic.candidates[0]
    assert candidate.outcome == "rejected"
    assert code in [reason.code for reason in candidate.reasons]
    assert candidate.driver_id is candidate.support_status is None


def test_kind_only_and_matching_all_labels(tmp_path):
    for labels in ({}, {"site": "lab", "role": "app"}):
        result = resolve_phase_provider(
            *inputs(tmp_path, [vm(), provider(), binding(labels=labels)]),
            metadata("example.driver"),
        )
        assert result.fact.status == "selected"
    result = resolve_phase_provider(
        *inputs(tmp_path, [vm(labels={}), provider(), binding()]),
        metadata("example.driver"),
    )
    assert result.fact.status == "selected"


def test_trace_collects_every_structural_reason_and_canonical_label_paths(tmp_path):
    args = inputs(
        tmp_path,
        [
            vm(),
            provider(),
            binding(
                capability="other",
                kind="Network",
                labels={"z": "missing", "site": "wrong", "a": "missing"},
            ),
        ],
    )
    diagnostic = failure(args, None, "no_matching_provider_binding")
    reasons = diagnostic.candidates[0].reasons
    assert [r.code for r in reasons] == [
        "capability_mismatch",
        "kind_mismatch",
        "missing_label",
        "label_mismatch",
        "missing_label",
    ]
    assert [r.field_path for r in reasons[2:]] == [
        ("spec", "match", "labels", "a"),
        ("spec", "match", "labels", "site"),
        ("spec", "match", "labels", "z"),
    ]
    assert reasons[3].expected == "wrong" and reasons[3].actual == "lab"


@pytest.mark.parametrize(
    "priorities", [(-100, -20), (-1, 0), (0, 5), (-3, 10), (2**64, 2**64 + 1)]
)
def test_highest_numeric_priority_wins_with_no_identity_or_specificity_score(
    tmp_path, priorities
):
    low, high = priorities
    args = inputs(
        tmp_path,
        [
            vm(),
            provider("a"),
            provider("z"),
            binding("a", "a", low, labels={"site": "lab", "role": "app"}),
            binding("z", "z", high),
        ],
    )
    result = resolve_phase_provider(*args, metadata("example.driver"))
    assert result.fact.selection.binding_identity == "ProviderBinding/z"
    assert result.fact.selection.provider_identity == "Provider/z"
    assert [c.outcome for c in result.fact.candidates] == ["outranked", "selected"]
    assert result.fact.candidates[0].reasons[0].code == "lower_priority"


@pytest.mark.parametrize("same_provider", [False, True])
def test_highest_priority_ties_are_ambiguous_even_for_same_provider(
    tmp_path, same_provider
):
    args = inputs(
        tmp_path,
        [
            vm(),
            provider("a"),
            provider("b"),
            binding("b", "a" if same_provider else "b", 100),
            binding("a", "a", 100, labels={"site": "lab"}),
            binding("low", "a", 50),
        ],
    )
    diagnostic = failure(args, metadata("example.driver"), "ambiguous_provider_binding")
    assert diagnostic.relevant_bindings == ("ProviderBinding/a", "ProviderBinding/b")
    assert [c.outcome for c in diagnostic.candidates] == [
        "ambiguous_highest_priority",
        "ambiguous_highest_priority",
        "outranked",
    ]
    assert [c.reasons[0].code for c in diagnostic.candidates[:2]] == [
        "highest_priority_tie"
    ] * 2


def test_multiple_provider_instances_sharing_driver_are_independent_candidates(
    tmp_path,
):
    args = inputs(
        tmp_path,
        [
            vm(),
            provider("one"),
            provider("two"),
            binding("one", "one", 5),
            binding("two", "two", 10),
        ],
    )
    result = resolve_phase_provider(*args, metadata("example.driver"))
    assert result.fact.selection.provider_identity == "Provider/two"
    assert {c.driver_id for c in result.fact.candidates} == {"example.driver"}
    assert {c.provider_identity for c in result.fact.candidates} == {
        "Provider/one",
        "Provider/two",
    }


def test_no_bindings_is_distinct_from_no_supported_bindings(tmp_path):
    args = inputs(tmp_path, [vm()])
    diagnostic = failure(args, None, "no_matching_provider_binding")
    assert diagnostic.candidates == ()
    args = inputs(tmp_path)
    diagnostic = failure(
        args,
        metadata("example.driver", unsupported=("example.driver",)),
        "no_supported_provider_binding",
    )
    assert diagnostic.candidates[0].support_status == "declared_unsupported"
    assert diagnostic.candidates[0].outcome == "unsupported"
    assert diagnostic.relevant_bindings == ("ProviderBinding/primary",)


@pytest.mark.parametrize("support", [None, DriverSupportMetadata(())])
def test_all_matching_drivers_missing_metadata_is_uncertainty(tmp_path, support):
    diagnostic = failure(inputs(tmp_path), support, "missing_driver_support_metadata")
    assert diagnostic.relevant_bindings == ("ProviderBinding/primary",)
    assert diagnostic.candidates[0].driver_id == "example.driver"
    assert diagnostic.candidates[0].support_status == "metadata_unavailable"


@pytest.mark.parametrize(
    "unknown_priority,blocks", [(101, True), (100, True), (99, False), (-1, False)]
)
def test_unknown_higher_or_equal_priority_blocks_but_lower_does_not(
    tmp_path, unknown_priority, blocks
):
    args = inputs(
        tmp_path,
        [
            vm(),
            provider("known", "known.driver"),
            provider("unknown", "unknown.driver"),
            binding("known", "known", 100),
            binding("unknown", "unknown", unknown_priority),
        ],
    )
    support = metadata("known.driver")
    if blocks:
        diagnostic = failure(args, support, "missing_driver_support_metadata")
        assert diagnostic.relevant_bindings == ("ProviderBinding/unknown",)
        assert diagnostic.candidates[0].outcome == "supported_unresolved"
        assert diagnostic.candidates[0].reasons[0].code == "selection_uncertain"
    else:
        result = resolve_phase_provider(*args, support)
        assert result.fact.selection.provider_identity == "Provider/known"
        unknown = result.fact.candidates[1]
        assert unknown.outcome == "metadata_unavailable"
        assert [r.code for r in unknown.reasons] == [
            "driver_metadata_unavailable",
            "lower_priority",
        ]


@pytest.mark.parametrize(
    "unknown_priority,code",
    [
        (11, "missing_driver_support_metadata"),
        (10, "missing_driver_support_metadata"),
        (9, "ambiguous_provider_binding"),
    ],
)
def test_unknown_decisive_metadata_precedes_definitive_ambiguity(
    tmp_path, unknown_priority, code
):
    args = inputs(
        tmp_path,
        [
            vm(),
            provider("known", "known.driver"),
            provider("unknown", "unknown.driver"),
            binding("a", "known", 10),
            binding("b", "known", 10),
            binding("unknown", "unknown", unknown_priority),
        ],
    )
    diagnostic = failure(args, metadata("known.driver"), code)
    expected = (
        "supported_unresolved"
        if code == "missing_driver_support_metadata"
        else "ambiguous_highest_priority"
    )
    assert [c.outcome for c in diagnostic.candidates[:2]] == [expected, expected]


def test_unsupported_high_priority_never_blocks_lower_supported(tmp_path):
    args = inputs(
        tmp_path,
        [
            vm(),
            provider("yes", "yes.driver"),
            provider("no", "no.driver"),
            binding("high", "no", 1000),
            binding("low", "yes", -5),
        ],
    )
    result = resolve_phase_provider(
        *args, metadata("yes.driver", "no.driver", unsupported=("no.driver",))
    )
    assert result.fact.selection.priority == -5
    assert result.fact.candidates[0].outcome == "unsupported"


def test_unknown_and_unsupported_with_no_supported_candidate_is_uncertainty(tmp_path):
    args = inputs(
        tmp_path,
        [
            vm(),
            provider("unknown", "unknown.driver"),
            provider("no", "no.driver"),
            binding("unknown", "unknown", -100),
            binding("no", "no", 100),
        ],
    )
    diagnostic = failure(
        args,
        metadata("no.driver", unsupported=("no.driver",)),
        "missing_driver_support_metadata",
    )
    assert diagnostic.relevant_bindings == ("ProviderBinding/unknown",)


@pytest.mark.parametrize("ownership", ["external", "disabled", None])
def test_nonmanaged_needs_no_binding_or_metadata_and_ignores_unused_inputs(
    tmp_path, ownership
):
    args = inputs(tmp_path, [vm(ownership=ownership)])
    for extra in ((None, None), (object(), object())):
        result = resolve_phase_provider(args[0], args[1], *extra)
        assert result.fact.status == (ownership or "unspecified")
        assert result.fact.selection is None and result.fact.candidates == ()
        assert set(result.sources) == {"VirtualMachine/app"}


def test_only_existing_explicit_phase_analysis_is_accepted(tmp_path):
    index, analysis, bindings = inputs(tmp_path)
    with pytest.raises(TypeError):
        resolve_phase_provider(index)
    for invalid in (
        None,
        PhaseRequest("VirtualMachine/app", "provision"),
        {},
        "provision",
    ):
        with pytest.raises(ProviderResolutionError) as caught:
            resolve_phase_provider(index, invalid, bindings, metadata("example.driver"))
        assert caught.value.diagnostic.code == "invalid_provider_resolution_input"
    with pytest.raises(ProviderResolutionError) as caught:
        resolve_phase_provider(index, analysis)
    assert caught.value.diagnostic.code == "invalid_provider_resolution_input"


def test_unsupported_managed_pair_stays_an_m27_diagnostic(tmp_path):
    data = {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": "x"},
        "spec": {"order": 0},
        "lifecycle": {"phases": {"provision": "managed"}},
    }
    path = write(tmp_path, [data])
    index = resolve_resources(load_yaml_files([path]))
    with pytest.raises(PhaseAnalysisError) as caught:
        analysis = analyze_phase_request(index, PhaseRequest("Stage/x", "provision"))
        resolve_phase_provider(index, analysis)
    assert caught.value.diagnostic.code == "unsupported_managed_phase"


def test_consistency_rejects_changed_phase_resource_and_provenance(tmp_path):
    index, analysis, declarations = inputs(tmp_path)
    resource = index.resources["VirtualMachine/app"].resource
    variants = [
        replace(
            index,
            resources={
                k: v for k, v in index.resources.items() if k != "VirtualMachine/app"
            },
        ),
        replace(
            index,
            resources={
                **index.resources,
                "VirtualMachine/app": index.resources["Provider/primary"],
            },
        ),
    ]
    for invalid in variants:
        failure(
            (invalid, analysis, declarations), None, "invalid_provider_resolution_input"
        )
    for invalid in (
        replace(analysis, fact=replace(analysis.fact, required_capability="other")),
        replace(analysis, fact=replace(analysis.fact, ownership="external")),
        replace(analysis, source=replace(analysis.source, document_index=99)),
    ):
        failure(
            (index, invalid, declarations), None, "invalid_provider_resolution_input"
        )
    resource.lifecycle.phases.provision = "external"
    failure((index, analysis, declarations), None, "invalid_provider_resolution_input")


@pytest.mark.parametrize(
    "corruption",
    [
        "missing",
        "duplicate",
        "priority",
        "capability",
        "labels",
        "field",
        "sources",
        "extra_source",
    ],
)
def test_corrupted_binding_snapshots_are_controlled(tmp_path, corruption):
    index, analysis, declarations = inputs(tmp_path)
    declaration = declarations.declarations[0]
    if corruption == "missing":
        invalid = replace(declarations, declarations=())
    elif corruption == "duplicate":
        invalid = replace(declarations, declarations=(declaration, declaration))
    elif corruption == "sources":
        invalid = replace(declarations, sources={})
    elif corruption == "extra_source":
        invalid = replace(
            declarations,
            sources={
                **declarations.sources,
                "Provider/stale": next(iter(declarations.sources.values())),
            },
        )
    else:
        changes = {
            "priority": {"priority": True},
            "capability": {"capability": "other"},
            "labels": {"match_labels": {"site": 42}},
            "field": {"field_path": ("spec", "other")},
        }
        invalid = replace(
            declarations, declarations=(replace(declaration, **changes[corruption]),)
        )
    failure(
        (index, analysis, invalid),
        metadata("example.driver"),
        "invalid_provider_resolution_input",
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_provider",
        "wrong_provider",
        "provider_identity",
        "binding_identity",
        "binding_spec",
        "priority",
        "binding_source",
        "provider_source",
        "driver",
        "labels",
    ],
)
def test_corrupted_index_inputs_do_not_leak_python_exceptions(tmp_path, corruption):
    index, analysis, declarations = inputs(tmp_path)
    entries = dict(index.resources)
    target = entries["Provider/primary"]
    owner = entries["ProviderBinding/primary"]
    if corruption == "missing_provider":
        del entries["Provider/primary"]
    elif corruption == "wrong_provider":
        entries["Provider/primary"] = entries["VirtualMachine/app"]
    elif corruption == "provider_identity":
        target.resource.metadata.name = "changed"
    elif corruption == "binding_identity":
        owner.resource.metadata.name = "changed"
    elif corruption == "binding_spec":
        owner.resource.spec = {}
    elif corruption == "priority":
        owner.resource.spec.priority = True
    elif corruption == "driver":
        target.resource.spec.driver = 12
    elif corruption == "labels":
        entries["VirtualMachine/app"].resource.metadata.labels = {"x": 1}
    else:
        key = (
            "ProviderBinding/primary"
            if corruption == "binding_source"
            else "Provider/primary"
        )
        entries[key] = replace(entries[key], source=None)
    failure(
        (replace(index, resources=entries), analysis, declarations),
        metadata("example.driver"),
        "invalid_provider_resolution_input",
    )


@pytest.mark.parametrize(
    "corruption", ["object", "descriptors", "duplicate", "capabilities", "driver"]
)
def test_malformed_supplied_metadata_is_controlled(tmp_path, corruption):
    support = metadata("example.driver")
    if corruption == "object":
        support = {}
    elif corruption == "descriptors":
        object.__setattr__(support, "descriptors", (object(),))
    elif corruption == "duplicate":
        object.__setattr__(support, "descriptors", support.descriptors * 2)
    elif corruption == "capabilities":
        object.__setattr__(
            support.descriptors[0], "capabilities", (CAPABILITY, CAPABILITY)
        )
    else:
        object.__setattr__(support.descriptors[0], "driver_id", False)
    failure(inputs(tmp_path), support, "invalid_provider_resolution_input")


def test_stale_binding_and_source_changes_are_rejected(tmp_path):
    index, analysis, declarations = inputs(tmp_path)
    index.resources["ProviderBinding/primary"].resource.spec.priority += 1
    failure((index, analysis, declarations), None, "invalid_provider_resolution_input")
    index, analysis, declarations = inputs(tmp_path)
    sources = dict(declarations.sources)
    sources["Provider/primary"] = replace(sources["Provider/primary"], line=999)
    failure(
        (index, analysis, replace(declarations, sources=sources)),
        None,
        "invalid_provider_resolution_input",
    )


def test_sources_are_document_roots_and_errors_include_relevant_origins(tmp_path):
    args = inputs(tmp_path)
    with pytest.raises(ProviderResolutionError) as caught:
        resolve_phase_provider(*args)
    diagnostic = caught.value.diagnostic
    assert diagnostic.phase == args[1].fact
    for identity, source in diagnostic.sources.items():
        original = args[0].resources[identity].source
        assert (
            source.source_path,
            source.document_index,
            source.line,
            source.column,
        ) == (
            original.source_path,
            original.document_index,
            original.line,
            original.column,
        )
        assert source is not original
    message = str(caught.value)
    assert "root line" in message and "document 3" in message
    assert "binding=ProviderBinding/primary" in message
    assert "driver=example.driver" in message
    assert "spec.provider" not in message  # Paths are available as structured tuples.
    assert diagnostic.candidates[0].reasons[0].field_path == ("spec", "provider")


@pytest.mark.parametrize("scenario", ["selected", "ambiguous", "uncertain"])
def test_portable_results_and_diagnostics_ignore_layout_and_declaration_order(
    tmp_path, scenario
):
    docs = [
        vm(),
        provider("a", "known.driver"),
        provider("b", "other.driver"),
        binding("a", "a", 100),
        binding("b", "b", 100 if scenario != "selected" else 1),
    ]
    support = metadata(
        "known.driver", *(() if scenario == "uncertain" else ("other.driver",))
    )
    first = inputs(tmp_path, docs)
    directory = tmp_path / "relocated"
    directory.mkdir()
    paths = [
        write(directory, [document], f"{number}.yml")
        for number, document in enumerate(reversed(docs))
    ]
    second = pipeline(paths)

    def portable(args):
        if scenario == "selected":
            return resolve_phase_provider(*args, support).fact
        diagnostic = failure(
            args,
            support,
            "ambiguous_provider_binding"
            if scenario == "ambiguous"
            else "missing_driver_support_metadata",
        )
        return (
            diagnostic.code,
            diagnostic.phase,
            diagnostic.candidates,
            diagnostic.relevant_bindings,
        )

    assert portable(first) == portable(second)
    assert [
        c.binding_identity
        for c in (
            portable(first).candidates if scenario == "selected" else portable(first)[2]
        )
    ] == ["ProviderBinding/a", "ProviderBinding/b"]


def test_deep_immutability_detached_inputs_and_no_config_retention(tmp_path):
    data = [vm(), provider(), binding(labels={"site": "lab"})]
    data[1]["spec"]["config"] = {"secret_ref": {"nested": ["opaque-reference-only"]}}
    index, analysis, declarations = inputs(tmp_path, data)
    before = {k: deepcopy(v.resource.model_dump()) for k, v in index.resources.items()}
    support = metadata("example.driver")
    result = resolve_phase_provider(index, analysis, declarations, support)
    assert {k: v.resource.model_dump() for k, v in index.resources.items()} == before
    with pytest.raises(FrozenInstanceError):
        result.fact.selection.priority = 0
    with pytest.raises(FrozenInstanceError):
        result.fact.candidates[0].reasons[0].code = "changed"
    with pytest.raises(TypeError):
        result.sources["new"] = next(iter(result.sources.values()))
    with pytest.raises(TypeError):
        result.fact.candidates[0].match_labels["site"] = "changed"
    for entry in index.resources.values():
        entry.resource.metadata.name = "mutated"
    index.resources["Provider/primary"].resource.spec.driver = "changed.driver"
    index.resources["Provider/primary"].resource.spec.config.clear()
    index.resources["VirtualMachine/app"].resource.metadata.labels.clear()
    assert result.fact.selection.driver_id == "example.driver"
    assert result.fact.candidates[0].match_labels == {"site": "lab"}
    assert "opaque-reference-only" not in repr(result)
    assert not isinstance(result.fact.selection, ResourceBase)
    with pytest.raises(FrozenInstanceError):
        result.sources["Provider/primary"].document_index = 0


def test_configuration_is_never_inspected_even_on_errors(tmp_path):
    args = inputs(tmp_path)
    # Deliberately unusable config: selection only consumes the already typed driver ID.
    args[0].resources["Provider/primary"].resource.spec.config = object()
    assert (
        resolve_phase_provider(*args, metadata("example.driver")).fact.status
        == "selected"
    )
    diagnostic = failure(args, None, "missing_driver_support_metadata")
    assert "config=" not in repr(diagnostic)


def test_large_candidate_set_is_iterative_and_preserves_every_binding(tmp_path):
    count = 1100
    args = inputs(
        tmp_path,
        [
            vm(),
            provider(),
            *(binding(f"b{i:04}", priority=i - 500) for i in range(count)),
        ],
    )
    result = resolve_phase_provider(*args, metadata("example.driver"))
    assert len(result.fact.candidates) == count
    assert result.fact.selection.binding_identity == "ProviderBinding/b1099"
    assert sum(c.outcome == "outranked" for c in result.fact.candidates) == count - 1


def test_case_sensitive_query_and_driver_support(tmp_path):
    args = inputs(
        tmp_path, [vm("App"), provider(), binding()], identity="VirtualMachine/App"
    )
    assert (
        resolve_phase_provider(
            *args, metadata("example.driver")
        ).fact.phase.request.resource_identity
        == "VirtualMachine/App"
    )
    failure(args, metadata("Example.driver"), "missing_driver_support_metadata")
    with pytest.raises(PhaseAnalysisError):
        analyze_phase_request(args[0], PhaseRequest("VirtualMachine/app", "provision"))


def test_full_infrastructure_pipeline_is_unchanged_by_resolution(tmp_path):
    root = Path(__file__).resolve().parents[1]
    extra = write(tmp_path, [provider(), binding()])
    index = resolve_resources(
        load_yaml_files(
            [
                root / "examples/infrastructure/resources.yml",
                root / "tests/fixtures/reference-stages.yml",
                extra,
            ]
        )
    )
    vm_identity = next(k for k in index.resources if k.startswith("VirtualMachine/"))
    index.resources[vm_identity].resource.lifecycle.phases.provision = "managed"
    analysis = analyze_phase_request(index, PhaseRequest(vm_identity, "provision"))
    declarations = validate_provider_bindings(index)
    normalized = normalize_resources(index)
    facts = classify_dependencies(index)
    graph = build_dependency_graph(index, facts)
    order = analyze_stage_order(index, graph)
    resolution = resolve_phase_provider(
        index, analysis, declarations, metadata("example.driver")
    )
    assert resolution.fact.status == "selected"
    assert normalized == normalize_resources(index)
    assert facts == classify_dependencies(index)
    assert graph == build_dependency_graph(index, facts)
    assert order == analyze_stage_order(index, graph)
    assert all(edge.prerequisite_identity != "Provider/primary" for edge in graph.edges)


def test_existing_clis_do_not_resolve_managed_bindings_or_write_state(tmp_path):
    path = write(tmp_path, [vm(), provider(), binding("a"), binding("b")])
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    runner = CliRunner()
    validate = runner.invoke(app, ["validate", str(path)])
    assert validate.exit_code == 0 and validate.stderr == ""
    assert validate.stdout == "Validated 4 resources; resolved 0 declared references.\n"
    graph = runner.invoke(app, ["graph", str(path)])
    assert graph.exit_code == 0 and graph.stderr == ""
    assert (
        "dependency edges: 0; declared reasons: 0; Stage assignments: 0" in graph.stdout
    )
    assert "ProviderBinding/a" in graph.stdout and "ProviderBinding/b" in graph.stdout
    args = pipeline([path])
    failure(args, metadata("example.driver"), "ambiguous_provider_binding")
    assert runner.invoke(app, ["validate", str(path)]).stdout == validate.stdout
    assert runner.invoke(app, ["graph", str(path)]).stdout == graph.stdout
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize(
    "lifecycle,origin",
    [
        ("omitted", "lifecycle_omitted"),
        (None, "lifecycle_null"),
        ({}, "phases_omitted"),
        ({"phases": None}, "phases_null"),
        ({"phases": {}}, "phase_omitted"),
        ({"phases": {"provision": None}}, "phase_null"),
    ],
)
def test_unspecified_origins_survive_resolution_without_selection(
    tmp_path, lifecycle, origin
):
    document = vm()
    if lifecycle == "omitted":
        del document["lifecycle"]
    else:
        document["lifecycle"] = lifecycle
    index, analysis, _ = inputs(tmp_path, [document])
    result = resolve_phase_provider(index, analysis)
    assert result.fact.status == "unspecified"
    assert result.fact.phase.ownership_origin == origin
    assert result.fact.phase.required_capability is None
    assert result.fact.selection is None and result.fact.candidates == ()


@pytest.mark.parametrize("desired_state", ["present", "absent"])
@pytest.mark.parametrize("prevent_destroy", [False, True])
def test_desired_state_and_safety_policy_do_not_influence_explicit_selection(
    tmp_path, desired_state, prevent_destroy
):
    args = inputs(
        tmp_path,
        [
            vm(
                lifecycle={
                    "desired_state": desired_state,
                    "prevent_destroy": prevent_destroy,
                    "phases": {"provision": "managed"},
                }
            ),
            provider(),
            binding(),
        ],
    )
    result = resolve_phase_provider(*args, metadata("example.driver"))
    assert result.fact.selection.provider_identity == "Provider/primary"
    # Only the requested phase appears, even if other lifecycle properties exist.
    assert result.fact.phase.request.phase == "provision"


def test_error_records_are_detached_and_deeply_immutable(tmp_path):
    args = inputs(
        tmp_path, [vm(), provider(), binding("a", labels={"site": "lab"}), binding("b")]
    )
    diagnostic = failure(args, metadata("example.driver"), "ambiguous_provider_binding")
    before = repr(diagnostic)
    for entry in args[0].resources.values():
        entry.resource.metadata.name = "changed"
    args[0].resources["ProviderBinding/a"].resource.spec.match.labels.clear()
    assert repr(diagnostic) == before
    with pytest.raises(FrozenInstanceError):
        diagnostic.code = "changed"
    with pytest.raises(TypeError):
        diagnostic.candidates[0].match_labels["site"] = "changed"
    with pytest.raises(TypeError):
        del diagnostic.sources["Provider/primary"]
