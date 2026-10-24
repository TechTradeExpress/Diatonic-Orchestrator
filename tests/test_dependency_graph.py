"""Logical graphs preserve origins and reject cycles without changing validation."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from diatonic.cli import app
from diatonic.compiler.dependencies import classify_dependencies
from diatonic.compiler.graph import (
    DependencyCycleError,
    DependencyGraphInputError,
    build_dependency_graph,
)
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.normalize import normalize_resources
from diatonic.compiler.references import resolve_resources

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/infrastructure/resources.yml"
STAGES = ROOT / "tests/fixtures/reference-stages.yml"


def stage(name, dependencies=()):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": name},
        "spec": {"order": 0},
        "depends_on": list(dependencies),
    }


def inputs(tmp_path, resources):
    path = tmp_path / "resources.yml"
    path.write_text(yaml.safe_dump_all(resources), encoding="utf-8")
    docs = load_yaml_files([path])
    index = resolve_resources(docs)
    return index, classify_dependencies(index)


def portable(graph):
    return graph.vertices, graph.edges, dict(graph.successors), graph.stage_assignments


def test_full_infrastructure_and_detached_provenance():
    docs = load_yaml_files([EXAMPLE, STAGES])
    before = deepcopy(docs)
    index = resolve_resources(docs)
    ir = normalize_resources(index)
    graph = build_dependency_graph(index, classify_dependencies(index))
    assert graph.vertices == tuple(sorted(index.resources))
    assert [(e.prerequisite_identity, e.dependent_identity) for e in graph.edges] == [
        ("Hypervisor/host01", "VirtualMachine/app01"),
        ("Image/debian13", "VirtualMachine/app01"),
        ("Network/servers", "VirtualMachine/app01"),
    ]
    assert graph.successors["Stage/platform"] == ()
    assert len(graph.stage_assignments) == 2
    assert set(graph.sources) == set(graph.vertices) == set(graph.successors)
    for identity, source in graph.sources.items():
        original = index.resources[identity].source
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
    assert docs == before
    snapshot, ir_snapshot = portable(graph), ir.to_json()
    docs[3].data["metadata"]["name"] = "changed"
    index.resources["VirtualMachine/app01"].resource.metadata.name = "changed"
    index.resources["VirtualMachine/app01"].resource.spec.interfaces.clear()
    assert portable(graph) == snapshot
    assert ir.to_json() == ir_snapshot
    with pytest.raises(FrozenInstanceError):
        graph.vertices = ()
    with pytest.raises(TypeError):
        graph.successors["Stage/platform"] = ()
    with pytest.raises(TypeError):
        graph.sources["new"] = None
    with pytest.raises(FrozenInstanceError):
        graph.edges[0].reasons[0].field_path = ()
    with pytest.raises(FrozenInstanceError):
        graph.sources["Stage/platform"].line = 99
    for record in (graph, graph.edges[0], graph.edges[0].reasons[0]):
        assert not hasattr(record, "__dict__")


def test_all_reasons_numeric_indexes_and_explicit_stage():
    docs = load_yaml_files([EXAMPLE, STAGES])
    docs[3].data["depends_on"] = [
        "Network/servers",
        "Network/servers",
        "Stage/workloads",
    ]
    docs[3].data["spec"]["interfaces"] = [
        {"name": f"nic{i}", "network": "Network/servers"} for i in range(12)
    ]
    index = resolve_resources(docs)
    facts = classify_dependencies(index)
    graph = build_dependency_graph(index, facts)
    edge = next(e for e in graph.edges if e.prerequisite_identity == "Network/servers")
    assert len(edge.reasons) == 14
    assert [r.field_path for r in edge.reasons] == [
        ("depends_on", 0),
        ("depends_on", 1),
        *[("spec", "interfaces", i, "network") for i in range(12)],
    ]
    assert [r.classification for r in edge.reasons] == ["explicit"] * 2 + [
        "implicit"
    ] * 12
    assert any(e.prerequisite_identity == "Stage/workloads" for e in graph.edges)
    assert graph == build_dependency_graph(
        replace(index, references=tuple(reversed(index.references))),
        replace(facts, dependencies=tuple(reversed(facts.dependencies))),
    )


def test_empty_and_isolated_resources(tmp_path):
    index = resolve_resources([])
    graph = build_dependency_graph(index, classify_dependencies(index))
    assert portable(graph) == ((), (), {}, ())
    index, facts = inputs(tmp_path, [stage("same"), stage("Same")])
    graph = build_dependency_graph(index, facts)
    assert graph.vertices == ("Stage/Same", "Stage/same")
    assert graph.edges == ()
    assert len(graph.sources) == 2


@pytest.mark.parametrize(
    "resources,witness",
    [
        ([stage("a", ["Stage/a"])], ("Stage/a", "Stage/a")),
        (
            [stage("a", ["Stage/b"]), stage("b", ["Stage/a"])],
            ("Stage/a", "Stage/b", "Stage/a"),
        ),
        (
            [stage("a", ["Stage/c"]), stage("b", ["Stage/a"]), stage("c", ["Stage/b"])],
            ("Stage/a", "Stage/b", "Stage/c", "Stage/a"),
        ),
        # Sorted DFS enters via a -> z; rotate b -> z -> c -> b, never reverse.
        (
            [
                stage("a"),
                stage("z", ["Stage/a", "Stage/b"]),
                stage("c", ["Stage/z"]),
                stage("b", ["Stage/c"]),
                stage("d", ["Stage/d"]),
            ],
            ("Stage/b", "Stage/z", "Stage/c", "Stage/b"),
        ),
    ],
)
def test_deterministic_directed_cycles(tmp_path, resources, witness):
    for declarations in (resources, list(reversed(resources))):
        index, facts = inputs(tmp_path, declarations)
        with pytest.raises(DependencyCycleError) as caught:
            build_dependency_graph(index, facts)
        error = caught.value
        assert error.code == "dependency_cycle"
        assert error.diagnostic.witness == witness
        assert [
            (e.prerequisite_identity, e.dependent_identity)
            for e in error.diagnostic.edges
        ] == list(zip(witness[:-1], witness[1:], strict=True))
        assert set(error.diagnostic.sources) == set(witness)
        for edge in error.diagnostic.edges:
            assert edge.reasons == tuple(
                f
                for f in facts.dependencies
                if (f.prerequisite_identity, f.dependent_identity)
                == (edge.prerequisite_identity, edge.dependent_identity)
            )
        assert "document" in str(error) and "root line" in str(error)
        with pytest.raises(TypeError):
            error.diagnostic.sources["new"] = None


def test_implicit_cycle_retains_all_reasons():
    docs = load_yaml_files([EXAMPLE, STAGES])
    docs[0].data["depends_on"] = ["VirtualMachine/app01"]
    docs[3].data["depends_on"] = ["Network/servers", "Network/servers"]
    index = resolve_resources(docs)
    with pytest.raises(DependencyCycleError) as caught:
        build_dependency_graph(index, classify_dependencies(index))
    assert caught.value.diagnostic.witness == (
        "Network/servers",
        "VirtualMachine/app01",
        "Network/servers",
    )
    assert len(caught.value.diagnostic.edges[0].reasons) == 3
    assert [r.classification for r in caught.value.diagnostic.edges[0].reasons] == [
        "explicit",
        "explicit",
        "implicit",
    ]


def test_file_layout_and_declaration_order_do_not_affect_portable_graph(tmp_path):
    docs = load_yaml_files([EXAMPLE, STAGES])
    index = resolve_resources(docs)
    baseline = build_dependency_graph(index, classify_dependencies(index))
    paths = []
    for i, doc in enumerate(reversed(docs)):
        path = tmp_path / f"renamed-{i}.yml"
        path.write_text(yaml.safe_dump(doc.data), encoding="utf-8")
        paths.append(path)
    for order in (paths, list(reversed(paths))):
        index = resolve_resources(load_yaml_files(order))
        graph = build_dependency_graph(index, classify_dependencies(index))
        assert portable(graph) == portable(baseline)
        assert graph.sources != baseline.sources


def test_long_chain_uses_no_python_recursion(tmp_path):
    resources = [
        stage(f"n{i:04}", [f"Stage/n{i - 1:04}"] if i else []) for i in range(2000)
    ]
    index, facts = inputs(tmp_path, resources)
    graph = build_dependency_graph(index, facts)
    assert len(graph.vertices) == 2000
    assert len(graph.edges) == 1999


@pytest.mark.parametrize(
    "change,message",
    [
        ({"prerequisite_identity": "Stage/missing"}, "unknown prerequisite"),
        ({"dependent_identity": "Stage/missing"}, "unknown dependent"),
        ({"resource_identity": "Stage/missing"}, "unknown owner"),
        ({"resource_identity": "Stage/a"}, "owner must equal dependent"),
        ({"classification": "implicit"}, "incompatible dependency"),
        ({"field_path": ("depends_on", -1)}, "invalid fact field path"),
    ],
)
def test_inconsistent_facts_are_controlled(tmp_path, change, message):
    index, facts = inputs(tmp_path, [stage("a"), stage("b", ["Stage/a"])])
    corrupt = replace(facts, dependencies=(replace(facts.dependencies[0], **change),))
    with pytest.raises(DependencyGraphInputError, match=message) as caught:
        build_dependency_graph(index, corrupt)
    assert caught.value.code == "invalid_graph_input"


def test_missing_or_incompatible_provenance_and_reference_counts(tmp_path):
    index, facts = inputs(tmp_path, [stage("a"), stage("b", ["Stage/a"])])
    for corrupt, message in [
        (replace(facts, sources={}), "missing fact owner provenance"),
        (replace(facts, sources={"Stage/b": None}), "missing required"),
        (
            replace(
                facts, sources={"Stage/b": replace(facts.sources["Stage/b"], line=999)}
            ),
            "provenance mismatch",
        ),
        (replace(facts, dependencies=()), "1 missing, 0 extra"),
        (replace(facts, dependencies=facts.dependencies * 2), "0 missing, 1 extra"),
    ]:
        with pytest.raises(DependencyGraphInputError, match=message):
            build_dependency_graph(index, corrupt)
    entries = dict(index.resources)
    entries["Stage/a"] = replace(entries["Stage/a"], source=None)
    with pytest.raises(DependencyGraphInputError, match="missing required"):
        build_dependency_graph(replace(index, resources=entries), facts)
    index.resources["Stage/a"].resource.metadata.name = "changed"
    with pytest.raises(DependencyGraphInputError, match="index key disagrees"):
        build_dependency_graph(index, facts)


def test_incompatible_stage_assignment_and_reference_source():
    index = resolve_resources(load_yaml_files([EXAMPLE, STAGES]))
    facts = classify_dependencies(index)
    assignment = replace(facts.stage_assignments[0], stage_identity="Network/servers")
    with pytest.raises(DependencyGraphInputError, match="incompatible Stage target"):
        build_dependency_graph(index, replace(facts, stage_assignments=(assignment,)))
    reference = replace(index.references[0], source=None)
    with pytest.raises(DependencyGraphInputError, match="missing required"):
        build_dependency_graph(replace(index, references=(reference,)), facts)
    with pytest.raises(TypeError, match="ResourceIndex"):
        build_dependency_graph({}, facts)


def test_cli_validate_still_accepts_cycle_declarations(tmp_path):
    inputs(tmp_path, [stage("a", ["Stage/b"]), stage("b", ["Stage/a"])])
    result = CliRunner().invoke(app, ["validate", str(tmp_path / "resources.yml")])
    assert result.exit_code == 0
    assert not result.stderr


def test_result_owns_all_mapping_containers():
    index = resolve_resources(load_yaml_files([EXAMPLE, STAGES]))
    graph = build_dependency_graph(index, classify_dependencies(index))
    successors = {key: list(value) for key, value in graph.successors.items()}
    sources = dict(graph.sources)
    copied = replace(graph, successors=successors, sources=sources)
    successors["Network/servers"].clear()
    successors.clear()
    sources.clear()
    assert copied == graph
    with pytest.raises(FrozenInstanceError):
        graph.edges[0].dependent_identity = "changed"
    with pytest.raises(FrozenInstanceError):
        graph.stage_assignments[0].stage_identity = "changed"


def test_minimal_vm_same_names_and_stage_order_are_not_interpreted(tmp_path):
    resources = [
        stage("same"),
        stage("later"),
        {
            "api_version": "iac/v0alpha1",
            "kind": "VirtualMachine",
            "metadata": {"name": "same"},
            "spec": {"cpu": {"cores": 1}, "memory": {"mib": 1}},
        },
    ]
    resources[0]["lifecycle"] = {"stage": "same"}
    resources[0]["depends_on"] = ["Stage/later"]
    resources[1]["spec"]["order"] = 50
    index, facts = inputs(tmp_path, resources)
    graph = build_dependency_graph(index, facts)
    assert graph.vertices == ("Stage/later", "Stage/same", "VirtualMachine/same")
    assert len(graph.edges) == 1
    assert graph.edges[0].prerequisite_identity == "Stage/later"
    assert graph.successors["VirtualMachine/same"] == ()
    assert graph.stage_assignments[0].stage_identity == "Stage/same"


def test_unknown_index_records_and_recorded_endpoints_are_controlled(tmp_path):
    index, facts = inputs(tmp_path, [stage("a"), stage("b", ["Stage/a"])])
    with pytest.raises(DependencyGraphInputError, match="missing indexed resource"):
        build_dependency_graph(replace(index, resources={"Stage/a": None}), facts)
    unknown = replace(index.references[0], target_identity="Stage/missing")
    with pytest.raises(DependencyGraphInputError, match="unknown endpoints"):
        build_dependency_graph(replace(index, references=(unknown,)), facts)
    unknown_source = replace(
        facts, sources={"Stage/missing": next(iter(facts.sources.values()))}
    )
    with pytest.raises(DependencyGraphInputError, match="unknown fact source owner"):
        build_dependency_graph(index, unknown_source)
