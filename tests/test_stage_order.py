"""Stage ranks constrain offline ordering, independently from declared edges."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path

import pytest
import yaml
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from diatonic.cli import app
from diatonic.compiler.dependencies import classify_dependencies
from diatonic.compiler.graph import DependencyCycleError, build_dependency_graph
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.normalize import normalize_resources
from diatonic.compiler.references import resolve_resources
from diatonic.compiler.stages import (
    StageOrderConflictError,
    StageOrderInputError,
    analyze_stage_order,
)

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/infrastructure/resources.yml"
STAGES = ROOT / "tests/fixtures/reference-stages.yml"


def stage(name, order=0, **fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": name},
        "spec": {"order": order},
        **fields,
    }


def vm(name, assigned=None, depends=()):
    resource = {
        "api_version": "iac/v0alpha1",
        "kind": "VirtualMachine",
        "metadata": {"name": name},
        "spec": {"cpu": {"cores": 1}, "memory": {"mib": 1}},
        "depends_on": list(depends),
    }
    if assigned is not None:
        resource["lifecycle"] = {"stage": assigned}
    return resource


def pipeline(documents):
    index = resolve_resources(documents)
    graph = build_dependency_graph(index, classify_dependencies(index))
    return index, graph


def inputs(tmp_path, resources):
    path = tmp_path / "resources.yml"
    path.write_text(yaml.safe_dump_all(resources), encoding="utf-8")
    return pipeline(load_yaml_files([path]))


def portable(result):
    return result.order, dict(result.stage_orders), dict(result.assignments)


def test_empty_and_isolated_stage_declarations(tmp_path):
    result = analyze_stage_order(*pipeline([]))
    assert portable(result) == ((), {}, {})
    assert dict(result.sources) == {}
    index, graph = inputs(tmp_path, [stage("z", -10), stage("A", 40), stage("a", 0)])
    result = analyze_stage_order(index, graph)
    assert result.order == ("Stage/A", "Stage/a", "Stage/z")
    assert result.stage_orders == {"Stage/A": 40, "Stage/a": 0, "Stage/z": -10}
    assert not result.assignments  # Stage declarations do not rank themselves.


def test_strict_groups_equal_ranks_negative_zero_and_multiple_members(tmp_path):
    index, graph = inputs(
        tmp_path,
        [
            stage("negative", -5),
            stage("zero"),
            stage("same", 0),
            stage("late", 30),
            vm("a", "late"),
            vm("b", "zero", ["VirtualMachine/c"]),
            vm("c", "same"),
            vm("y", "negative"),
            vm("z", "negative"),
        ],
    )
    result = analyze_stage_order(index, graph)
    assert result.order == (
        "Stage/late",
        "Stage/negative",
        "Stage/same",
        "Stage/zero",
        "VirtualMachine/y",
        "VirtualMachine/z",
        "VirtualMachine/c",
        "VirtualMachine/b",
        "VirtualMachine/a",
    )
    assert len(graph.edges) == 1
    assert all(e.reasons[0].classification == "explicit" for e in graph.edges)
    assert len(result.assignments) == 5


def test_unassigned_can_interleave_and_stage_vertices_can_be_explicitly_ranked(
    tmp_path,
):
    index, graph = inputs(
        tmp_path,
        [
            stage("early", -1),
            stage("late", 5),
            stage("unassigned", 100, depends_on=["VirtualMachine/c"]),
            stage("ranked", 900, lifecycle={"stage": "early"}),
            vm("a"),
            vm("b", "early"),
            vm("c"),
            vm("d", "late"),
            vm("e"),
        ],
    )
    result = analyze_stage_order(index, graph)
    assert result.order == (
        "Stage/early",
        "Stage/late",
        "Stage/ranked",
        "VirtualMachine/a",
        "VirtualMachine/b",
        "VirtualMachine/c",
        "Stage/unassigned",
        "VirtualMachine/d",
        "VirtualMachine/e",
    )
    assert result.assignments["Stage/ranked"].order == -1
    assert result.stage_orders["Stage/ranked"] == 900
    assert "Stage/unassigned" not in result.assignments
    assert "VirtualMachine/a" not in result.assignments


def test_unassigned_prerequisite_of_early_group_remains_eligible(tmp_path):
    index, graph = inputs(
        tmp_path,
        [
            stage("early", 10),
            stage("late", 40),
            vm("a", "late"),
            vm("b", "early", ["VirtualMachine/z"]),
            vm("z"),
        ],
    )
    result = analyze_stage_order(index, graph)
    assert result.order[-3:] == (
        "VirtualMachine/z",
        "VirtualMachine/b",
        "VirtualMachine/a",
    )


def conflict_resources(indirect=False):
    return [
        stage("early", 10),
        stage("late", 40),
        vm("app", "late"),
        vm(
            "base",
            "early",
            ["VirtualMachine/helper" if indirect else "VirtualMachine/app"],
        ),
        *([vm("helper", depends=["VirtualMachine/app"])] if indirect else []),
    ]


@pytest.mark.parametrize("indirect", [False, True])
def test_direct_and_indirect_conflict_with_full_origins(tmp_path, indirect):
    index, graph = inputs(tmp_path, conflict_resources(indirect))
    with pytest.raises(StageOrderConflictError) as caught:
        analyze_stage_order(index, graph)
    error = caught.value
    diagnostic = error.diagnostic
    assert error.code == "stage_order_conflict"
    expected = (
        "VirtualMachine/app",
        *(["VirtualMachine/helper"] if indirect else []),
        "VirtualMachine/base",
    )
    assert diagnostic.witness == expected
    assert (
        diagnostic.higher.resource_identity,
        diagnostic.higher.stage_identity,
        diagnostic.higher.order,
    ) == ("VirtualMachine/app", "Stage/late", 40)
    assert (
        diagnostic.lower.resource_identity,
        diagnostic.lower.stage_identity,
        diagnostic.lower.order,
    ) == ("VirtualMachine/base", "Stage/early", 10)
    assert (
        diagnostic.higher.field_path
        == diagnostic.lower.field_path
        == ("lifecycle", "stage")
    )
    assert [
        (e.prerequisite_identity, e.dependent_identity) for e in diagnostic.edges
    ] == list(zip(expected[:-1], expected[1:], strict=True))
    for edge in diagnostic.edges:
        assert edge in graph.edges
        assert all(reason.field_path == ("depends_on", 0) for reason in edge.reasons)
    assert set(diagnostic.sources) == {*expected, "Stage/early", "Stage/late"}
    for identity, source in diagnostic.sources.items():
        assert source == graph.sources[identity]
        assert source is not graph.sources[identity]
    assert "root line" in str(error) and "order=40" in str(error)
    assert "field=('lifecycle', 'stage')" in str(error)


@pytest.mark.parametrize(
    "target,path",
    [
        ("Hypervisor/host01", ("spec", "placement", "target")),
        ("Network/servers", ("spec", "interfaces", 0, "network")),
        ("Image/debian13", ("spec", "image", "ref")),
    ],
)
def test_backwards_implicit_dependencies_and_all_reasons(target, path):
    docs = load_yaml_files([EXAMPLE, STAGES])
    for document in docs:
        document.data.pop("lifecycle", None)
        identity = f"{document.data['kind']}/{document.data['metadata']['name']}"
        if identity == target:
            document.data["lifecycle"] = {"stage": "workloads"}
        if identity == "VirtualMachine/app01":
            document.data["lifecycle"] = {"stage": "platform"}
            document.data["depends_on"] = [target, target]
    index, graph = pipeline(docs)
    with pytest.raises(StageOrderConflictError) as caught:
        analyze_stage_order(index, graph)
    diagnostic = caught.value.diagnostic
    assert diagnostic.witness == (target, "VirtualMachine/app01")
    assert [r.field_path for r in diagnostic.edges[0].reasons] == [
        ("depends_on", 0),
        ("depends_on", 1),
        path,
    ]
    assert [r.classification for r in diagnostic.edges[0].reasons] == [
        "explicit",
        "explicit",
        "implicit",
    ]


def test_conflict_ties_follow_dependency_order_rank_owner_and_first_predecessor(
    tmp_path,
):
    resources = [
        stage("early", 10),
        stage("late", 40),
        stage("latest", 50),
        vm("a", "late"),
        vm("b", "latest"),
        vm("c", "latest"),
        vm("helper-a", depends=["VirtualMachine/b", "VirtualMachine/c"]),
        vm("helper-b", depends=["VirtualMachine/b"]),
        vm(
            "z",
            "early",
            ["VirtualMachine/helper-b", "VirtualMachine/helper-a", "VirtualMachine/a"],
        ),
        vm("zz", "early", ["VirtualMachine/a"]),
    ]
    diagnostics = []
    for declarations in (resources, list(reversed(resources))):
        index, graph = inputs(tmp_path, declarations)
        with pytest.raises(StageOrderConflictError) as caught:
            analyze_stage_order(index, graph)
        diagnostics.append(caught.value.diagnostic)
    for diagnostic in diagnostics:
        assert diagnostic.witness == (
            "VirtualMachine/b",
            "VirtualMachine/helper-a",
            "VirtualMachine/z",
        )
        assert diagnostic.higher.order == 50
    assert diagnostics[0].witness == diagnostics[1].witness
    assert diagnostics[0].edges == diagnostics[1].edges


def test_dependency_cycles_still_fail_in_graph_builder_first(tmp_path):
    resources = conflict_resources()
    resources[2]["depends_on"] = ["VirtualMachine/base"]
    with pytest.raises(DependencyCycleError) as caught:
        index, graph = inputs(tmp_path, resources)
        analyze_stage_order(index, graph)
    assert caught.value.code == "dependency_cycle"


def test_full_example_layout_independence_and_isolation(tmp_path):
    docs = load_yaml_files([EXAMPLE, STAGES])
    before = deepcopy(docs)
    index, graph = pipeline(docs)
    facts = classify_dependencies(index)
    ir = normalize_resources(index)
    before_ir = ir.to_json()
    result = analyze_stage_order(index, graph)
    assert result.order == (
        "Hypervisor/host01",
        "Image/debian13",
        "Network/servers",
        "Stage/platform",
        "Stage/workloads",
        "VirtualMachine/app01",
    )
    assert result.assignments["Hypervisor/host01"].order == 20
    assert result.assignments["VirtualMachine/app01"].order == 40
    assert docs == before
    assert facts == classify_dependencies(index)
    assert graph == build_dependency_graph(index, facts)
    assert before_ir == ir.to_json()
    paths = []
    for i, document in enumerate(reversed(docs)):
        directory = tmp_path / str(i)
        directory.mkdir()
        path = directory / "relocated.yml"
        path.write_text(yaml.safe_dump(document.data), encoding="utf-8")
        paths.append(path)
    for order in (paths, list(reversed(paths))):
        relocated = analyze_stage_order(*pipeline(load_yaml_files(order)))
        assert portable(relocated) == portable(result)
        assert relocated.sources != result.sources
    snapshot = portable(result)
    docs[-1].data["spec"]["order"] = -999
    index.resources["Stage/platform"].resource.spec.order = 999
    index.resources["Stage/platform"].resource.metadata.name = "changed"
    index.resources["VirtualMachine/app01"].resource.lifecycle.stage = "changed"
    assert portable(result) == snapshot
    assert before_ir == ir.to_json()
    with pytest.raises(FrozenInstanceError):
        result.order = ()
    with pytest.raises(TypeError):
        result.assignments["new"] = None
    with pytest.raises(TypeError):
        result.stage_orders["Stage/platform"] = 0
    with pytest.raises(TypeError):
        result.sources["new"] = None
    with pytest.raises(FrozenInstanceError):
        result.assignments["Hypervisor/host01"].order = 0
    with pytest.raises(FrozenInstanceError):
        result.sources["Stage/platform"].line = 999
    for record in (
        result,
        result.assignments["Hypervisor/host01"],
        result.sources["Stage/platform"],
    ):
        assert not hasattr(record, "__dict__")
    mappings = {
        name: dict(getattr(result, name))
        for name in ("assignments", "stage_orders", "sources")
    }
    copied = replace(result, **mappings)
    for mapping in mappings.values():
        mapping.clear()
    assert copied == result


def test_long_mixed_rank_and_unassigned_chain(tmp_path):
    resources = [stage(f"rank{i}", i - 500) for i in range(1000)]
    resources += [
        vm(
            f"n{i:04}",
            f"rank{i // 2}" if i % 2 == 0 else None,
            [f"VirtualMachine/n{i - 1:04}"] if i else [],
        )
        for i in range(2000)
    ]
    index, graph = inputs(tmp_path, resources)
    result = analyze_stage_order(index, graph)
    assert len(result.order) == 3000
    assert result.order[-2000:] == tuple(f"VirtualMachine/n{i:04}" for i in range(2000))
    assert len(graph.edges) == 1999  # No cross-group expansion.


def test_conflict_diagnostic_is_immutable_and_detached(tmp_path):
    index, graph = inputs(tmp_path, conflict_resources(True))
    with pytest.raises(StageOrderConflictError) as caught:
        analyze_stage_order(index, graph)
    diagnostic = caught.value.diagnostic
    with pytest.raises(FrozenInstanceError):
        diagnostic.higher.order = 0
    with pytest.raises(FrozenInstanceError):
        diagnostic.witness = ()
    with pytest.raises(TypeError):
        diagnostic.sources["new"] = None
    with pytest.raises(FrozenInstanceError):
        diagnostic.edges[0].reasons[0].classification = "implicit"
    index.resources["Stage/late"].resource.spec.order = -1
    assert diagnostic.higher.order == 40
    assert diagnostic.witness[0] == "VirtualMachine/app"


def test_cli_validate_is_unchanged_for_stage_conflicts(tmp_path):
    inputs(tmp_path, conflict_resources())
    result = CliRunner().invoke(app, ["validate", str(tmp_path / "resources.yml")])
    assert result.exit_code == 0
    assert not result.stderr


@settings(
    max_examples=75,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
@given(
    ranks=st.lists(st.sampled_from([None, -1, 0, 1]), min_size=5, max_size=5),
    links=st.sets(st.sampled_from([(a, b) for a in range(5) for b in range(a + 1, 5)])),
)
def test_small_dags_match_explicit_precedence_oracle(tmp_path, ranks, links):
    resources = [stage("r-1", -1), stage("r0", 0), stage("r1", 1)]
    resources += [
        vm(
            str(i),
            f"r{rank}" if rank is not None else None,
            [f"VirtualMachine/{a}" for a, b in sorted(links) if b == i],
        )
        for i, rank in enumerate(ranks)
    ]
    index, graph = inputs(tmp_path, resources)
    prerequisites = {v: set() for v in graph.vertices}
    for edge in graph.edges:
        prerequisites[edge.dependent_identity].add(edge.prerequisite_identity)
    for i, rank in enumerate(ranks):
        if rank is not None:
            for j, other in enumerate(ranks):
                if other is not None and other < rank:
                    prerequisites[f"VirtualMachine/{i}"].add(f"VirtualMachine/{j}")
    expected = []
    while prerequisites:
        ready = sorted(v for v, deps in prerequisites.items() if not deps)
        if not ready:
            with pytest.raises(StageOrderConflictError):
                analyze_stage_order(index, graph)
            break
        node = ready[0]
        expected.append(node)
        del prerequisites[node]
        for deps in prerequisites.values():
            deps.discard(node)
    else:
        assert analyze_stage_order(index, graph).order == tuple(expected)


def test_explicit_stage_dependency_does_not_rank_its_target(tmp_path):
    index, graph = inputs(
        tmp_path,
        [
            stage("early", -10),
            stage("late", 900),
            vm("a", "early", ["Stage/late"]),
            vm("z", "early", ["VirtualMachine/a"]),
        ],
    )
    result = analyze_stage_order(index, graph)
    assert result.order == (
        "Stage/early",
        "Stage/late",
        "VirtualMachine/a",
        "VirtualMachine/z",
    )
    assert "Stage/late" not in result.assignments
    assert len(graph.edges) == 2
    assert graph.edges[0].prerequisite_identity == "Stage/late"


@pytest.mark.parametrize(
    "corruption,message",
    [
        ("vertices", "vertex mismatch"),
        ("sources", "missing vertex provenance"),
        ("source-value", "document-root provenance"),
        ("provenance", "provenance mismatch"),
        ("assignment-owner", "unknown assignment owner"),
        ("assignment-target", "missing/wrong-kind Stage"),
        ("assignment-path", "invalid Stage assignment"),
        ("assignment-duplicate", "duplicate or invalid"),
        ("assignment-omitted", "Stage assignment mismatch"),
        ("reason-omitted", "do not match index references"),
        ("adjacency", "adjacency mismatch"),
        ("edge-endpoint", "invalid, duplicate or unexplained"),
        ("edge-duplicate", "invalid, duplicate or unexplained"),
        ("edge-empty", "invalid, duplicate or unexplained"),
        ("reason-owner", "reason endpoints/category mismatch"),
    ],
)
def test_incompatible_graphs_have_controlled_errors(corruption, message):
    index, graph = pipeline(load_yaml_files([EXAMPLE, STAGES]))
    if corruption == "vertices":
        graph = replace(graph, vertices=graph.vertices[:-1])
    elif corruption == "sources":
        graph = replace(graph, sources={})
    elif corruption in {"source-value", "provenance"}:
        sources = dict(graph.sources)
        sources["Stage/platform"] = (
            None
            if corruption == "source-value"
            else replace(sources["Stage/platform"], line=999)
        )
        graph = replace(graph, sources=sources)
    elif corruption.startswith("assignment-"):
        assignment = graph.stage_assignments[0]
        changes = {
            "assignment-owner": {"resource_identity": "VirtualMachine/missing"},
            "assignment-target": {"stage_identity": "Hypervisor/host01"},
            "assignment-path": {"field_path": ("lifecycle", "other")},
        }
        assignments = graph.stage_assignments
        if corruption == "assignment-duplicate":
            assignments += (assignment,)
        elif corruption == "assignment-omitted":
            assignments = assignments[1:]
        else:
            assignments = (replace(assignment, **changes[corruption]), *assignments[1:])
        graph = replace(graph, stage_assignments=assignments)
    elif corruption == "reason-omitted":
        index = replace(index, references=index.references[:-1])
    elif corruption == "adjacency":
        successors = dict(graph.successors)
        successors["Hypervisor/host01"] = ()
        graph = replace(graph, successors=successors)
    else:
        edge = graph.edges[0]
        if corruption == "edge-endpoint":
            edge = replace(edge, prerequisite_identity="Network/missing")
        elif corruption == "edge-empty":
            edge = replace(edge, reasons=())
        elif corruption == "reason-owner":
            edge = replace(
                edge,
                reasons=(replace(edge.reasons[0], resource_identity="Stage/platform"),),
            )
        edges = (
            (*graph.edges, edge)
            if corruption == "edge-duplicate"
            else (edge, *graph.edges[1:])
        )
        graph = replace(graph, edges=edges)
    with pytest.raises(StageOrderInputError, match=message) as caught:
        analyze_stage_order(index, graph)
    assert caught.value.code == "invalid_stage_order_input"


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("identity", "identity mismatch"),
        ("order-bool", "strict integer order"),
        ("order-string", "strict integer order"),
        ("order-null", "strict integer order"),
        ("stage-spec", "strict integer order"),
        ("assignment", "Stage assignment mismatch"),
        ("lifecycle", "expected validated lifecycle"),
        ("source", "document-root provenance"),
    ],
)
def test_detectable_index_mutations_fail_explicitly(mutation, message):
    index, graph = pipeline(load_yaml_files([EXAMPLE, STAGES]))
    resource = index.resources["Stage/platform"].resource
    if mutation == "identity":
        resource.metadata.name = "changed"
    elif mutation.startswith("order-"):
        resource.spec.order = {
            "order-bool": True,
            "order-string": "20",
            "order-null": None,
        }[mutation]
    elif mutation == "stage-spec":
        resource.spec = {"order": 20}
    elif mutation == "assignment":
        index.resources["VirtualMachine/app01"].resource.lifecycle.stage = "platform"
    elif mutation == "lifecycle":
        resource.lifecycle = {}
    else:
        entries = dict(index.resources)
        entries["Stage/platform"] = replace(entries["Stage/platform"], source=None)
        index = replace(index, resources=entries)
    with pytest.raises(StageOrderInputError, match=message):
        analyze_stage_order(index, graph)


def test_current_stage_order_is_snapshotted_not_historical_graph_order(tmp_path):
    index, graph = inputs(tmp_path, [stage("rank", -1), vm("a", "rank")])
    before = analyze_stage_order(index, graph)
    # Graphs have no historical Stage-order snapshot; callers must not mutate
    # compiler inputs. A valid integer edit cannot be distinguished from new input.
    index.resources["Stage/rank"].resource.spec.order = 100
    after = analyze_stage_order(index, graph)
    assert before.assignments["VirtualMachine/a"].order == -1
    assert after.assignments["VirtualMachine/a"].order == 100


def test_wrong_stage_model_and_index_records_are_controlled(tmp_path):
    from diatonic.model.base import ResourceBase

    index, graph = inputs(tmp_path, [stage("rank"), vm("a", "rank")])
    entries = dict(index.resources)
    entries["Stage/rank"] = replace(
        entries["Stage/rank"], resource=ResourceBase.model_validate(stage("rank"))
    )
    with pytest.raises(StageOrderInputError, match="expected validated Stage"):
        analyze_stage_order(replace(index, resources=entries), graph)
    entries["Stage/rank"] = None
    with pytest.raises(StageOrderInputError, match="identity mismatch"):
        analyze_stage_order(replace(index, resources=entries), graph)
    with pytest.raises(TypeError, match="ResourceIndex and DependencyGraph"):
        analyze_stage_order({}, graph)
    with pytest.raises(TypeError, match="ResourceIndex and DependencyGraph"):
        analyze_stage_order(index, {})


def test_index_reference_provenance_and_endpoints_are_checked(tmp_path):
    index, graph = inputs(tmp_path, [stage("a"), stage("b", depends_on=["Stage/a"])])
    ref = index.references[0]
    for invalid, message in [
        (replace(ref, target_identity="Stage/missing"), "unknown endpoints"),
        (replace(ref, source=replace(ref.source, line=999)), "provenance mismatch"),
        (replace(ref, field_path=("depends_on", True)), "invalid recorded field path"),
    ]:
        with pytest.raises(StageOrderInputError, match=message):
            analyze_stage_order(replace(index, references=(invalid,)), graph)


def test_conflict_file_layout_and_numeric_origins_are_preserved(tmp_path):
    docs = load_yaml_files([EXAMPLE, STAGES])
    docs[0].data["lifecycle"] = {"stage": "workloads"}
    docs[3].data["lifecycle"]["stage"] = "platform"
    docs[3].data["depends_on"] = ["Network/servers"] * 2
    docs[3].data["spec"]["interfaces"] = [
        {"name": f"nic{i}", "network": "Network/servers"} for i in range(12)
    ]
    paths = []
    for i, document in enumerate(reversed(docs)):
        path = tmp_path / f"different-{i}.yml"
        path.write_text(yaml.safe_dump(document.data), encoding="utf-8")
        paths.append(path)
    diagnostics = []
    for documents in (
        docs,
        load_yaml_files(paths),
        load_yaml_files(list(reversed(paths))),
    ):
        with pytest.raises(StageOrderConflictError) as caught:
            analyze_stage_order(*pipeline(documents))
        diagnostics.append(caught.value.diagnostic)
    assert all(d.witness == diagnostics[0].witness for d in diagnostics)
    assert all(d.edges == diagnostics[0].edges for d in diagnostics)
    assert diagnostics[0].sources != diagnostics[1].sources
    reasons = diagnostics[0].edges[0].reasons
    assert [r.field_path for r in reasons] == [
        ("depends_on", 0),
        ("depends_on", 1),
        *[("spec", "interfaces", i, "network") for i in range(12)],
    ]


def test_late_to_early_conflict_through_long_unassigned_chain(tmp_path):
    resources = [stage("early", 1), stage("late", 2), vm("start", "late")]
    previous = "VirtualMachine/start"
    for i in range(1200):
        name = f"helper{i:04}"
        resources.append(vm(name, depends=[previous]))
        previous = f"VirtualMachine/{name}"
    resources.append(vm("end", "early", [previous]))
    with pytest.raises(StageOrderConflictError) as caught:
        analyze_stage_order(*inputs(tmp_path, resources))
    assert len(caught.value.diagnostic.witness) == 1202
    assert len(caught.value.diagnostic.edges) == 1201
    assert caught.value.diagnostic.witness[0] == "VirtualMachine/start"
    assert caught.value.diagnostic.witness[-1] == "VirtualMachine/end"
