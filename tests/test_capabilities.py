"""Explicit offline capability demand and independent supplied driver facts."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from diatonic.cli import app
from diatonic.compiler.capabilities import (
    CAPABILITY_VOCABULARY,
    DriverSupportDescriptor,
    DriverSupportError,
    DriverSupportMetadata,
    PhaseAnalysisError,
    PhaseRequest,
    analyze_phase_request,
    assess_driver_support,
)
from diatonic.compiler.dependencies import classify_dependencies
from diatonic.compiler.graph import build_dependency_graph
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.normalize import normalize_resources
from diatonic.compiler.provider_bindings import validate_provider_bindings
from diatonic.compiler.references import resolve_resources
from diatonic.compiler.stages import analyze_stage_order
from diatonic.model.base import ResourceBase

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/infrastructure/resources.yml"
STAGES = ROOT / "tests/fixtures/reference-stages.yml"
PHASES = ("observe", "provision", "configure")
SPECS = {
    "VirtualMachine": {"cpu": {"cores": 1}, "memory": {"mib": 512}},
    "Network": {
        "vlan_id": 10,
        "ipv4": {"cidr": "192.0.2.0/24", "gateway": "192.0.2.1"},
    },
    "Hypervisor": {"management": {"address": "192.0.2.10"}},
    "Image": {
        "os": {
            "family": "linux",
            "distribution": "example",
            "version": "1",
            "architecture": "example",
        }
    },
    "Stage": {"order": 20},
    "Provider": {"driver": "example.unregistered", "config": {}},
    "ProviderBinding": {
        "capability": "virtual_machine.provision",
        "match": {"kind": "VirtualMachine"},
        "provider": "Provider/target",
        "priority": 100,
    },
}
EXPECTED = {
    ("VirtualMachine", "observe"): "virtual_machine.observe",
    ("VirtualMachine", "provision"): "virtual_machine.provision",
    ("VirtualMachine", "configure"): "virtual_machine.configure",
    ("Network", "observe"): "network.observe",
    ("Network", "provision"): "network.provision",
    ("Hypervisor", "observe"): "hypervisor.observe",
    ("Hypervisor", "configure"): "hypervisor.configure",
}
UNSUPPORTED = [
    (kind, phase) for kind in SPECS for phase in PHASES if (kind, phase) not in EXPECTED
]


def resource(kind="VirtualMachine", name="app", **fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": kind,
        "metadata": {"name": name},
        "spec": deepcopy(SPECS[kind]),
        **fields,
    }


def write(tmp_path, resources, filename="input.yml"):
    path = tmp_path / filename
    path.write_text(yaml.safe_dump_all(resources, sort_keys=False), encoding="utf-8")
    return path


def inputs(tmp_path, resources):
    path = write(tmp_path, resources)
    docs = load_yaml_files([path])
    return docs, resolve_resources(docs)


def query(index, identity="VirtualMachine/app", phase="provision"):
    return analyze_phase_request(index, PhaseRequest(identity, phase))


def test_vocabulary_is_exact_immutable_and_canonical():
    assert dict(CAPABILITY_VOCABULARY) == EXPECTED
    assert list(CAPABILITY_VOCABULARY) == sorted(EXPECTED)
    with pytest.raises(TypeError):
        CAPABILITY_VOCABULARY["Image", "provision"] = "image.provision"


@pytest.mark.parametrize("pair,capability", EXPECTED.items())
def test_every_supported_managed_mapping_needs_no_provider_or_metadata(
    tmp_path, pair, capability
):
    kind, phase = pair
    _, index = inputs(
        tmp_path, [resource(kind, lifecycle={"phases": {phase: "managed"}})]
    )
    result = query(index, f"{kind}/app", phase)
    assert result.fact.request == PhaseRequest(f"{kind}/app", phase)
    assert result.fact.ownership == "managed"
    assert result.fact.ownership_origin == "declared"
    assert result.fact.required_capability == capability
    assert len(index.resources) == 1


@pytest.mark.parametrize("kind,phase", UNSUPPORTED)
def test_every_unsupported_managed_pair_has_structured_source_diagnostic(
    tmp_path, kind, phase
):
    docs, index = inputs(
        tmp_path, [resource(kind, lifecycle={"phases": {phase: "managed"}})]
    )
    with pytest.raises(PhaseAnalysisError) as caught:
        query(index, f"{kind}/app", phase)
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "unsupported_managed_phase"
    assert diagnostic.resource_identity == f"{kind}/app"
    assert diagnostic.phase == phase
    assert diagnostic.field_path == ("lifecycle", "phases", phase)
    assert diagnostic.source.source_path == docs[0].source_path
    assert diagnostic.source.document_index == 1
    assert (diagnostic.source.line, diagnostic.source.column) == (1, 1)
    assert "root line" in str(caught.value)
    assert "document 1" in str(caught.value)


@pytest.mark.parametrize("kind", SPECS)
@pytest.mark.parametrize("phase", PHASES)
@pytest.mark.parametrize("ownership", ["external", "disabled", None])
def test_nonmanaged_outcomes_do_not_require_any_mapping_or_support(
    tmp_path, kind, phase, ownership
):
    _, index = inputs(
        tmp_path, [resource(kind, lifecycle={"phases": {phase: ownership}})]
    )
    result = query(index, f"{kind}/app", phase)
    assert result.fact.ownership == (ownership or "unspecified")
    assert result.fact.required_capability is None
    assert result.fact.ownership_origin == (
        "phase_null" if ownership is None else "declared"
    )


@pytest.mark.parametrize(
    "case,origin",
    [
        ("lifecycle_omitted", "lifecycle_omitted"),
        ("lifecycle_null", "lifecycle_null"),
        ("phases_omitted", "phases_omitted"),
        ("phases_null", "phases_null"),
        ("phase_omitted", "phase_omitted"),
        ("phase_null", "phase_null"),
    ],
)
@pytest.mark.parametrize("phase", PHASES)
def test_all_omitted_and_explicit_null_origins_are_preserved(
    tmp_path, case, origin, phase
):
    fields = {}
    if case == "lifecycle_null":
        fields = {"lifecycle": None}
    elif case == "phases_omitted":
        fields = {"lifecycle": {}}
    elif case == "phases_null":
        fields = {"lifecycle": {"phases": None}}
    elif case == "phase_omitted":
        fields = {"lifecycle": {"phases": {}}}
    elif case == "phase_null":
        fields = {"lifecycle": {"phases": {phase: None}}}
    docs, index = inputs(tmp_path, [resource(**fields)])
    before = deepcopy(docs)
    result = query(index, phase=phase)
    assert result.fact.ownership == "unspecified"
    assert result.fact.ownership_origin == origin
    assert result.fact.required_capability is None
    assert docs == before
    assert (
        index.resources["VirtualMachine/app"].resource.model_dump(exclude_unset=True)
        == docs[0].data
    )


@pytest.mark.parametrize("desired", ["present", "absent", None])
@pytest.mark.parametrize("prevent", [True, False, None])
@pytest.mark.parametrize("ownership", ["managed", None])
def test_desired_state_and_prevent_destroy_do_not_determine_demand(
    tmp_path, desired, prevent, ownership
):
    _, index = inputs(
        tmp_path,
        [
            resource(
                lifecycle={
                    "desired_state": desired,
                    "prevent_destroy": prevent,
                    "phases": {"provision": ownership},
                }
            )
        ],
    )
    result = query(index)
    assert result.fact.ownership == (ownership or "unspecified")
    assert result.fact.required_capability == (
        "virtual_machine.provision" if ownership == "managed" else None
    )


def test_only_requested_phase_and_resource_are_examined(tmp_path):
    _, index = inputs(
        tmp_path,
        [
            resource(
                "Stage",
                lifecycle={"phases": {"observe": "external", "provision": "managed"}},
            ),
            resource("ProviderBinding"),
        ],
    )
    # Stage/provision is unsupported; the unrequested binding target is missing.
    assert query(index, "Stage/app", "observe").fact.ownership == "external"
    assert query(index, "Stage/app", "observe").fact.required_capability is None
    index.resources["Stage/app"].resource.lifecycle.phases.provision = {
        "unrequested": "bad"
    }
    assert query(index, "Stage/app", "observe").fact.ownership == "external"


@pytest.mark.parametrize(
    "identity",
    ["VirtualMachine/missing", "VirtualMachine/App", "virtualmachine/app", "Stage/app"],
)
def test_unknown_and_wrong_case_identities_have_no_fallback(tmp_path, identity):
    _, index = inputs(tmp_path, [resource()])
    with pytest.raises(PhaseAnalysisError) as caught:
        query(index, identity)
    assert caught.value.diagnostic.code == "unknown_phase_resource"
    assert caught.value.diagnostic.resource_identity == identity
    assert caught.value.diagnostic.source is None


@pytest.mark.parametrize(
    "identity",
    [
        "app",
        "",
        "VirtualMachine/",
        "VirtualMachine/a/b",
        "VirtualMachine/bad name",
        None,
        1,
        True,
        [],
        {},
        b"VirtualMachine/app",
    ],
)
def test_invalid_resource_identity_requests_are_controlled(identity):
    with pytest.raises(PhaseAnalysisError) as caught:
        PhaseRequest(identity, "provision")
    assert caught.value.diagnostic.code == "invalid_phase_request"


@pytest.mark.parametrize(
    "phase", ["apply", "destroy", "Observe", "", None, True, 1, [], {}, b"provision"]
)
def test_invalid_phase_names_and_types_are_controlled(phase):
    with pytest.raises(PhaseAnalysisError) as caught:
        PhaseRequest("VirtualMachine/app", phase)
    assert caught.value.diagnostic.code == "invalid_phase_request"
    assert caught.value.diagnostic.resource_identity == "VirtualMachine/app"
    assert caught.value.diagnostic.source is None


def test_request_is_required_not_implicitly_created(tmp_path):
    _, index = inputs(
        tmp_path, [resource(lifecycle={"phases": {"provision": "managed"}})]
    )
    with pytest.raises(TypeError):
        analyze_phase_request(index)
    with pytest.raises(PhaseAnalysisError) as caught:
        analyze_phase_request(index, None)
    assert caught.value.diagnostic.code == "invalid_phase_request"


@pytest.mark.parametrize(
    "mutation",
    [
        "entry",
        "resource",
        "identity",
        "metadata",
        "kind",
        "lifecycle",
        "phases",
        "ownership",
        "source",
        "source_position",
        "presence",
        "missing_lifecycle",
        "missing_phases",
        "missing_ownership",
    ],
)
def test_corrupted_requested_inputs_have_controlled_diagnostics(tmp_path, mutation):
    _, index = inputs(
        tmp_path, [resource(lifecycle={"phases": {"provision": "managed"}})]
    )
    entry = index.resources["VirtualMachine/app"]
    model = entry.resource
    entries = dict(index.resources)
    if mutation == "entry":
        entries["VirtualMachine/app"] = None
    elif mutation == "resource":
        entries["VirtualMachine/app"] = replace(
            entry, resource=ResourceBase.model_validate(resource())
        )
    elif mutation == "identity":
        model.metadata.name = "changed"
    elif mutation == "metadata":
        model.metadata = None
    elif mutation == "kind":
        model.kind = []
    elif mutation == "lifecycle":
        model.lifecycle = {}
    elif mutation == "phases":
        model.lifecycle.phases = {}
    elif mutation == "ownership":
        model.lifecycle.phases.provision = "unknown"
    elif mutation == "source":
        entries["VirtualMachine/app"] = replace(entry, source=None)
    elif mutation == "missing_lifecycle":
        model.__dict__.pop("lifecycle")
    elif mutation == "missing_phases":
        model.lifecycle.__dict__.pop("phases")
    elif mutation == "missing_ownership":
        model.lifecycle.phases.__dict__.pop("provision")
    elif mutation == "source_position":
        entries["VirtualMachine/app"] = replace(
            entry, source=replace(entry.source, document_index=True)
        )
    else:
        model.lifecycle.phases.model_fields_set.remove("provision")
    with pytest.raises(PhaseAnalysisError) as caught:
        query(replace(index, resources=entries))
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "invalid_phase_input"
    assert diagnostic.resource_identity == "VirtualMachine/app"
    assert diagnostic.field_path == ("lifecycle", "phases", "provision")
    if mutation not in {"entry", "source", "source_position"}:
        assert diagnostic.source.source_path == entry.source.source_path
        assert diagnostic.source.line == 1


def test_malformed_index_and_unavailable_root_positions(tmp_path):
    _, index = inputs(
        tmp_path, [resource(lifecycle={"phases": {"provision": "managed"}})]
    )
    for malformed in ({}, replace(index, resources=[])):
        with pytest.raises(PhaseAnalysisError) as caught:
            query(malformed)
        assert caught.value.diagnostic.code == "invalid_phase_input"
    entry = index.resources["VirtualMachine/app"]
    entry = replace(entry, source=replace(entry.source, line=None, column=None))
    result = query(replace(index, resources={"VirtualMachine/app": entry}))
    assert result.source.line is result.source.column is None


def test_no_provider_configuration_is_in_phase_results_or_errors(tmp_path):
    data = resource(
        "Provider",
        lifecycle={"phases": {"observe": "external", "provision": "managed"}},
    )
    data["spec"]["config"] = {
        "credentials": {"token": {"secret_ref": "example/not-resolved"}}
    }
    _, index = inputs(tmp_path, [data])
    assert query(index, "Provider/app", "observe").fact.required_capability is None
    with pytest.raises(PhaseAnalysisError) as caught:
        query(index, "Provider/app", "provision")
    assert caught.value.diagnostic.code == "unsupported_managed_phase"
    assert "example/not-resolved" not in str(caught.value)
    assert "example.unregistered" not in str(caught.value)


def test_supplied_driver_metadata_three_states_and_empty_declarations():
    descriptor = DriverSupportDescriptor(
        "example.driver", ["virtual_machine.provision", "virtual_machine.observe"]
    )
    metadata = DriverSupportMetadata(
        [descriptor, DriverSupportDescriptor("empty.driver", ())]
    )
    assert descriptor.capabilities == (
        "virtual_machine.observe",
        "virtual_machine.provision",
    )
    assert (
        assess_driver_support(
            metadata, "example.driver", "virtual_machine.provision"
        ).status
        == "declared_supported"
    )
    assert (
        assess_driver_support(
            metadata, "example.driver", "virtual_machine.configure"
        ).status
        == "declared_unsupported"
    )
    assert (
        assess_driver_support(
            metadata, "missing.driver", "virtual_machine.provision"
        ).status
        == "metadata_unavailable"
    )
    assert (
        assess_driver_support(
            metadata, "empty.driver", "virtual_machine.provision"
        ).status
        == "declared_unsupported"
    )
    assert (
        assess_driver_support(
            DriverSupportMetadata(()), "example.driver", "virtual_machine.provision"
        ).status
        == "metadata_unavailable"
    )
    assert (
        assess_driver_support(
            metadata, "Example.driver", "virtual_machine.provision"
        ).status
        == "metadata_unavailable"
    )
    assert (
        assess_driver_support(
            metadata, "example.driver", "Virtual_machine.provision"
        ).status
        == "declared_unsupported"
    )


@pytest.mark.parametrize(
    "identifier", ["", " ", "a b", "a/b", None, True, 7, [], {}, b"id"]
)
@pytest.mark.parametrize("field", ["driver", "capability"])
def test_invalid_descriptor_identifiers_are_not_coerced(identifier, field):
    with pytest.raises(DriverSupportError) as caught:
        DriverSupportDescriptor(
            identifier if field == "driver" else "example.driver",
            (identifier,) if field == "capability" else (),
        )
    assert caught.value.diagnostic.code == "invalid_driver_descriptor"


@pytest.mark.parametrize(
    "values",
    [None, "virtual_machine.provision", b"cap", {}, {"cap"}, iter(["cap"]), True, 1],
)
def test_capability_collections_are_explicit_lists_or_tuples(values):
    with pytest.raises(DriverSupportError) as caught:
        DriverSupportDescriptor("example.driver", values)
    assert caught.value.diagnostic.code == "invalid_driver_descriptor"
    with pytest.raises(TypeError):
        DriverSupportDescriptor("example.driver")


@pytest.mark.parametrize(
    "values",
    [
        None,
        "example.driver",
        {},
        set(),
        [None],
        ["example.driver"],
        [object()],
        iter(()),
    ],
)
def test_metadata_collection_requires_explicit_descriptors(values):
    with pytest.raises(DriverSupportError) as caught:
        DriverSupportMetadata(values)
    assert caught.value.diagnostic.code == "invalid_driver_descriptor"


def test_duplicate_capabilities_and_drivers_are_canonical_errors():
    for capabilities in (["z", "a", "z", "a"], ["a", "z", "a", "z"]):
        with pytest.raises(DriverSupportError) as caught:
            DriverSupportDescriptor("example.driver", capabilities)
        assert caught.value.diagnostic.code == "duplicate_driver_capability"
        assert caught.value.diagnostic.capability == "a"
        assert caught.value.diagnostic.driver_id == "example.driver"
    descriptors = [
        DriverSupportDescriptor(driver, ()) for driver in ("z", "A", "a", "A", "z")
    ]
    for declarations in (descriptors, list(reversed(descriptors))):
        with pytest.raises(DriverSupportError) as caught:
            DriverSupportMetadata(declarations)
        assert caught.value.diagnostic.code == "duplicate_driver_descriptor"
        assert caught.value.diagnostic.driver_id == "A"


@pytest.mark.parametrize(
    "identifier", [None, 1, True, [], "", "with space", "Kind/name"]
)
@pytest.mark.parametrize("field", ["driver", "capability"])
def test_support_queries_validate_identifiers(identifier, field):
    metadata = DriverSupportMetadata(())
    with pytest.raises(DriverSupportError) as caught:
        assess_driver_support(
            metadata,
            identifier if field == "driver" else "example.driver",
            identifier if field == "capability" else "capability",
        )
    assert caught.value.diagnostic.code == "invalid_support_query"


def test_support_inspection_requires_supplied_metadata_not_provider_declarations():
    with pytest.raises(DriverSupportError) as caught:
        assess_driver_support([], "example.driver", "virtual_machine.provision")
    assert caught.value.diagnostic.code == "invalid_driver_descriptor"
    metadata = DriverSupportMetadata(
        [DriverSupportDescriptor("future.driver", ["arbitrary.future:capability"])]
    )
    assert (
        assess_driver_support(
            metadata, "future.driver", "arbitrary.future:capability"
        ).status
        == "declared_supported"
    )


def test_driver_metadata_is_owned_immutable_and_order_independent():
    capabilities = ["z", "A", "a"]
    descriptor = DriverSupportDescriptor("z.driver", capabilities)
    descriptors = [descriptor, DriverSupportDescriptor("A.driver", ())]
    metadata = DriverSupportMetadata(descriptors)
    assert [d.driver_id for d in metadata.descriptors] == ["A.driver", "z.driver"]
    assert metadata.descriptors[1].capabilities == ("A", "a", "z")
    assert metadata == DriverSupportMetadata(list(reversed(descriptors)))
    assessment = assess_driver_support(metadata, "z.driver", "A")
    capabilities.clear()
    descriptors.clear()
    assert metadata.descriptors[1].capabilities == ("A", "a", "z")
    assert descriptor.capabilities == ("A", "a", "z")
    assert assessment.status == "declared_supported"
    with pytest.raises(FrozenInstanceError):
        metadata.descriptors = ()
    with pytest.raises(FrozenInstanceError):
        descriptor.driver_id = "changed"
    with pytest.raises(FrozenInstanceError):
        assessment.status = "metadata_unavailable"
    for record in (descriptor, metadata, assessment):
        assert not hasattr(record, "__dict__")


def test_phase_analysis_is_detached_immutable_and_portable_across_layouts(tmp_path):
    data = resource(lifecycle={"phases": {"provision": "managed"}})
    docs, index = inputs(tmp_path, [data])
    before = deepcopy(docs)
    ir = normalize_resources(index)
    request = PhaseRequest("VirtualMachine/app", "provision")
    result = analyze_phase_request(index, request)
    renamed = write(tmp_path, [resource("Stage"), data], "renamed.yml")
    alternate = query(resolve_resources(load_yaml_files([renamed])))
    assert alternate.fact == result.fact
    assert alternate.source != result.source
    assert docs == before
    assert normalize_resources(index).to_json() == ir.to_json()
    original_source = index.resources["VirtualMachine/app"].source
    assert (
        result.source.source_path,
        result.source.document_index,
        result.source.line,
        result.source.column,
    ) == (
        original_source.source_path,
        original_source.document_index,
        original_source.line,
        original_source.column,
    )
    assert result.source is not original_source
    index.resources[
        "VirtualMachine/app"
    ].resource.lifecycle.phases.provision = "external"
    docs[0].data["lifecycle"]["phases"]["provision"] = "disabled"
    assert result.fact.required_capability == "virtual_machine.provision"
    assert result.fact.ownership == "managed"
    with pytest.raises(FrozenInstanceError):
        result.fact.ownership = "external"
    with pytest.raises(FrozenInstanceError):
        request.phase = "observe"
    with pytest.raises(FrozenInstanceError):
        result.source.line = 999
    for record in (result, result.fact, result.source, request):
        assert not hasattr(record, "__dict__")


def test_full_infrastructure_fixture_and_permutations():
    requests = [
        ("VirtualMachine/app01", "provision"),
        ("Hypervisor/host01", "observe"),
        ("Hypervisor/host01", "provision"),
        ("Network/servers", "observe"),
    ]
    results = []
    for paths in ([EXAMPLE, STAGES], [STAGES, EXAMPLE]):
        index = resolve_resources(load_yaml_files(paths))
        results.append([query(index, identity, phase) for identity, phase in requests])
    assert results[0] == results[1]
    assert [result.fact.ownership for result in results[0]] == [
        "managed",
        "managed",
        "external",
        "unspecified",
    ]
    assert [result.fact.required_capability for result in results[0]] == [
        "virtual_machine.provision",
        "hypervisor.observe",
        None,
        None,
    ]


def test_binding_graph_stage_and_ir_are_unchanged_by_explicit_queries(tmp_path):
    provider = resource(
        "Provider", "target", lifecycle={"phases": {"observe": "external"}}
    )
    binding = resource(
        "ProviderBinding",
        "binding",
        lifecycle={"stage": "platform", "phases": {"observe": "external"}},
        depends_on=["Provider/target"],
    )
    _, index = inputs(tmp_path, [binding, provider, resource("Stage", "platform")])
    declarations = validate_provider_bindings(index)
    facts = classify_dependencies(index)
    graph = build_dependency_graph(index, facts)
    stage_order = analyze_stage_order(index, graph)
    ir = normalize_resources(index)
    snapshots = {
        key: entry.resource.model_dump(exclude_unset=True)
        for key, entry in index.resources.items()
    }
    references = index.references
    assert (
        query(index, "ProviderBinding/binding", "observe").fact.ownership == "external"
    )
    assert query(index, "Provider/target", "observe").fact.ownership == "external"
    assert validate_provider_bindings(index) == declarations
    assert classify_dependencies(index) == facts
    assert build_dependency_graph(index, facts) == graph
    assert analyze_stage_order(index, graph) == stage_order
    assert normalize_resources(index).to_json() == ir.to_json()
    assert snapshots == {
        key: entry.resource.model_dump(exclude_unset=True)
        for key, entry in index.resources.items()
    }
    assert index.references is references
    assert [ref.field_path for ref in references] == [
        ("depends_on", 0),
        ("lifecycle", "stage"),
    ]
    assert len(graph.edges) == len(declarations.declarations) == 1


@pytest.mark.parametrize("command", ["validate", "graph"])
@pytest.mark.parametrize("desired", ["present", "absent"])
def test_cli_never_analyzes_managed_phases_implicitly(tmp_path, command, desired):
    # All three Stage phases have no mapping. Both CLIs must still accept the
    # declaration; only an explicit phase query is allowed to reject it.
    path = write(
        tmp_path,
        [
            resource(
                "Stage",
                lifecycle={
                    "desired_state": desired,
                    "prevent_destroy": True,
                    "phases": {phase: "managed" for phase in PHASES},
                },
            )
        ],
    )
    result = CliRunner().invoke(app, [command, str(path)])
    assert result.exit_code == 0 and result.stderr == ""
    if command == "validate":
        assert (
            result.stdout == "Validated 1 resource; resolved 0 declared references.\n"
        )
    else:
        assert (
            result.stdout
            == """Logical dependency graph (offline, not an execution plan)
Resources: 1; dependency edges: 0; declared reasons: 0; Stage assignments: 0

Vertices (1):
  Stage/app

Dependencies (0):
  (none)

Stage assignments (0):
  (none)

Topological order (1):
  1. Stage/app
"""
        )
    index = resolve_resources(load_yaml_files([path]))
    with pytest.raises(PhaseAnalysisError) as caught:
        query(index, "Stage/app", "observe")
    assert caught.value.diagnostic.code == "unsupported_managed_phase"


def test_library_analysis_and_support_inspection_do_not_write_files(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    path = write(tmp_path, [resource(lifecycle={"phases": {"provision": "managed"}})])
    index = resolve_resources(load_yaml_files([path]))
    before = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    result = query(index)
    metadata = DriverSupportMetadata(
        [
            DriverSupportDescriptor(
                "unregistered.future", [result.fact.required_capability]
            )
        ]
    )
    assert (
        assess_driver_support(
            metadata, "unregistered.future", result.fact.required_capability
        ).status
        == "declared_supported"
    )
    after = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    assert after == before
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


def test_diagnostic_root_location_and_literal_names_are_detached(tmp_path):
    data = resource("Image", "[red]image", lifecycle={"phases": {"observe": "managed"}})
    path = tmp_path / "[bold]input.yml"
    path.write_text("# comment\n---\n" + yaml.safe_dump(data), encoding="utf-8")
    index = resolve_resources(load_yaml_files([path]))
    with pytest.raises(PhaseAnalysisError) as caught:
        query(index, "Image/[red]image", "observe")
    diagnostic = caught.value.diagnostic
    assert (
        diagnostic.source.source_path,
        diagnostic.source.document_index,
        diagnostic.source.line,
        diagnostic.source.column,
    ) == (path, 1, 3, 1)
    assert str(path) in str(caught.value) and "Image/[red]image" in str(caught.value)
    assert "root line 3" in str(caught.value)
    with pytest.raises(FrozenInstanceError):
        diagnostic.code = "unknown_phase_resource"
    with pytest.raises(FrozenInstanceError):
        diagnostic.source.column = 999
    with pytest.raises(DriverSupportError) as support:
        DriverSupportDescriptor("duplicate.driver", ["a", "a"])
    with pytest.raises(FrozenInstanceError):
        support.value.diagnostic.capability = "changed"


def test_explicitly_supplied_ids_are_not_interpolated_or_inferred(tmp_path):
    data = resource("Provider")
    data["spec"]["driver"] = "${EXAMPLE_DRIVER}"
    provider_binding = resource("ProviderBinding")
    provider_binding["spec"]["provider"] = "Provider/app"
    _, index = inputs(tmp_path, [data, provider_binding])
    validate_provider_bindings(index)
    empty = DriverSupportMetadata(())
    assert (
        assess_driver_support(
            empty, "${EXAMPLE_DRIVER}", "virtual_machine.provision"
        ).status
        == "metadata_unavailable"
    )
    metadata = DriverSupportMetadata(
        [DriverSupportDescriptor("${EXAMPLE_DRIVER}", ["virtual_machine.provision"])]
    )
    assert (
        assess_driver_support(
            metadata, "${EXAMPLE_DRIVER}", "virtual_machine.provision"
        ).status
        == "declared_supported"
    )
    # Neither the Provider's driver nor the binding's capability populated metadata.
    assert empty.descriptors == ()
