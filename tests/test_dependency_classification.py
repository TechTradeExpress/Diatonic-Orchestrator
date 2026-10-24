"""M2.1 facts preserve resolved origins without graph or Stage-rank semantics."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import Any

import pytest
import yaml

from diatonic.compiler.dependencies import (
    DependencyClassificationError,
    DependencyFacts,
    classify_dependencies,
)
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.normalize import normalize_resources
from diatonic.compiler.references import resolve_resources

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/infrastructure/resources.yml"
STAGES = ROOT / "tests/fixtures/reference-stages.yml"


def stage(name: str, **overrides: Any) -> dict[str, Any]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": name},
        "spec": {"order": 0},
        **overrides,
    }


def vm(name: str = "app", **overrides: Any) -> dict[str, Any]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": "VirtualMachine",
        "metadata": {"name": name},
        "spec": {"cpu": {"cores": 1}, "memory": {"mib": 512}},
        **overrides,
    }


def load_resources(tmp_path: Path, resources: list[dict[str, Any]]):
    path = tmp_path / "resources.yml"
    path.write_text(yaml.safe_dump_all(resources, sort_keys=False), encoding="utf-8")
    return load_yaml_files([path])


def portable(facts: DependencyFacts):
    return facts.dependencies, facts.stage_assignments


def test_full_example_classifies_all_implicit_fields_and_stages() -> None:
    index = resolve_resources(load_yaml_files([EXAMPLE, STAGES]))
    facts = classify_dependencies(index)
    assert [
        (
            f.prerequisite_identity,
            f.dependent_identity,
            f.classification,
            f.resource_identity,
            f.field_path,
        )
        for f in facts.dependencies
    ] == [
        (
            "Hypervisor/host01",
            "VirtualMachine/app01",
            "implicit",
            "VirtualMachine/app01",
            ("spec", "placement", "target"),
        ),
        (
            "Network/servers",
            "VirtualMachine/app01",
            "implicit",
            "VirtualMachine/app01",
            ("spec", "interfaces", 0, "network"),
        ),
        (
            "Image/debian13",
            "VirtualMachine/app01",
            "implicit",
            "VirtualMachine/app01",
            ("spec", "image", "ref"),
        ),
    ]
    assert [
        (s.resource_identity, s.stage_identity, s.field_path)
        for s in facts.stage_assignments
    ] == [
        ("Hypervisor/host01", "Stage/platform", ("lifecycle", "stage")),
        ("VirtualMachine/app01", "Stage/workloads", ("lifecycle", "stage")),
    ]
    assert len(facts.dependencies) + len(facts.stage_assignments) == len(
        index.references
    )
    assert all(
        not f.prerequisite_identity.startswith("Stage/") for f in facts.dependencies
    )
    for ref in index.references:
        source = facts.sources[ref.resource_identity]
        assert (
            source.source_path,
            source.document_index,
            source.line,
            source.column,
        ) == (
            ref.source.source_path,
            ref.source.document_index,
            ref.source.line,
            ref.source.column,
        )
        assert source is not ref.source


def test_explicit_stage_dependency_is_distinct_from_stage_assignment(tmp_path: Path):
    docs = load_resources(
        tmp_path,
        [
            vm(depends_on=["Stage/workloads"], lifecycle={"stage": "workloads"}),
            stage("workloads"),
        ],
    )
    facts = classify_dependencies(resolve_resources(docs))
    assert len(facts.dependencies) == 1
    assert facts.dependencies[0].classification == "explicit"
    assert facts.dependencies[0].prerequisite_identity == "Stage/workloads"
    assert facts.dependencies[0].field_path == ("depends_on", 0)
    assert facts.stage_assignments[0].stage_identity == "Stage/workloads"
    assert facts.stage_assignments[0].field_path == ("lifecycle", "stage")


def test_same_pair_reasons_and_repeated_dependencies_are_not_collapsed() -> None:
    docs = load_yaml_files([EXAMPLE, STAGES])
    resource = docs[3].data
    resource["depends_on"] = ["Network/servers", "Network/servers", "Stage/workloads"]
    resource["spec"]["interfaces"] = [
        {"name": f"nic{i}", "network": "Network/servers"} for i in range(12)
    ]
    index = resolve_resources(docs)
    facts = classify_dependencies(index)
    assert len(facts.dependencies) == 17
    assert [f.classification for f in facts.dependencies[:3]] == ["explicit"] * 3
    assert [f.field_path for f in facts.dependencies] == [
        ("depends_on", 0),
        ("depends_on", 1),
        ("depends_on", 2),
        ("spec", "placement", "target"),
        *[("spec", "interfaces", i, "network") for i in range(12)],
        ("spec", "image", "ref"),
    ]
    same_pair = [
        f for f in facts.dependencies if f.prerequisite_identity == "Network/servers"
    ]
    assert len(same_pair) == 14
    assert len({f.field_path for f in same_pair}) == 14
    assert all(type(f.field_path[2]) is int for f in facts.dependencies[4:16])
    # Even an input record sequence permutation is canonicalized by path indexes.
    assert facts == classify_dependencies(
        replace(index, references=tuple(reversed(index.references)))
    )


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"lifecycle": None},
        {"lifecycle": {}},
        {
            "depends_on": [],
            "spec": {
                "cpu": {"cores": 1},
                "memory": {"mib": 1},
                "placement": None,
                "image": None,
                "interfaces": [],
            },
        },
    ],
)
def test_optional_sections_produce_no_guessed_relationships(tmp_path: Path, fields):
    facts = classify_dependencies(
        resolve_resources(load_resources(tmp_path, [vm(**fields)]))
    )
    assert facts.dependencies == ()
    assert facts.stage_assignments == ()
    assert dict(facts.sources) == {}


def test_same_names_across_kinds_and_case_are_preserved(tmp_path: Path) -> None:
    docs = load_resources(
        tmp_path,
        [
            stage("same"),
            stage("Same"),
            vm("same", depends_on=["Stage/same", "Stage/Same"]),
            vm("Same", depends_on=["VirtualMachine/same"]),
        ],
    )
    facts = classify_dependencies(resolve_resources(docs))
    assert [
        (f.dependent_identity, f.prerequisite_identity) for f in facts.dependencies
    ] == [
        ("VirtualMachine/Same", "VirtualMachine/same"),
        ("VirtualMachine/same", "Stage/same"),
        ("VirtualMachine/same", "Stage/Same"),
    ]


def test_portable_facts_independent_of_files_layout_and_forward_declarations(
    tmp_path: Path,
):
    docs = load_yaml_files([EXAMPLE, STAGES])
    baseline = classify_dependencies(resolve_resources(docs))
    paths = []
    for i, doc in enumerate(reversed(docs)):
        directory = tmp_path / str(i)
        directory.mkdir()
        path = directory / "renamed.yml"
        path.write_text(yaml.safe_dump(doc.data), encoding="utf-8")
        paths.append(path)
    relocated = classify_dependencies(resolve_resources(load_yaml_files(paths)))
    assert portable(relocated) == portable(baseline)
    assert relocated.sources != baseline.sources
    assert all(source.document_index == 1 for source in relocated.sources.values())
    assert portable(
        classify_dependencies(resolve_resources(load_yaml_files(list(reversed(paths)))))
    ) == portable(baseline)
    assert baseline == classify_dependencies(resolve_resources(list(reversed(docs))))


def test_stage_assignments_sort_by_owner_not_stage_order(tmp_path: Path) -> None:
    docs = load_resources(
        tmp_path,
        [
            vm("z", lifecycle={"stage": "early"}),
            vm("a", lifecycle={"stage": "late"}),
            stage("late", spec={"order": 40}),
            stage("early", spec={"order": -10}),
        ],
    )
    facts = classify_dependencies(resolve_resources(docs))
    assert [s.resource_identity for s in facts.stage_assignments] == [
        "VirtualMachine/a",
        "VirtualMachine/z",
    ]
    assert facts.dependencies == ()


def test_deep_immutability_and_input_isolation() -> None:
    docs = load_yaml_files([EXAMPLE, STAGES])
    before_docs = deepcopy(docs)
    index = resolve_resources(docs)
    before_models = {
        key: entry.resource.model_dump() for key, entry in index.resources.items()
    }
    original_references = index.references
    ir = normalize_resources(index)
    before_ir = ir.to_json()
    facts = classify_dependencies(index)
    snapshot = portable(facts)
    assert facts == classify_dependencies(index)
    assert docs == before_docs
    assert original_references is index.references
    assert {
        key: entry.resource.model_dump() for key, entry in index.resources.items()
    } == before_models
    assert normalize_resources(index).to_json() == before_ir

    docs[3].data["metadata"]["name"] = "changed"
    index.resources["VirtualMachine/app01"].resource.metadata.name = "changed"
    index.resources["VirtualMachine/app01"].resource.spec.interfaces.clear()
    assert portable(facts) == snapshot
    assert ir.to_json() == before_ir
    # Classification deliberately consumes recorded links, not mutable model state.
    assert facts == classify_dependencies(index)
    with pytest.raises(FrozenInstanceError):
        facts.dependencies = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        facts.dependencies[0].classification = "explicit"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        facts.stage_assignments[0].stage_identity = "Stage/changed"  # type: ignore[misc]
    with pytest.raises(TypeError):
        facts.sources["VirtualMachine/app01"] = facts.sources["VirtualMachine/app01"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        facts.sources["VirtualMachine/app01"].line = 999  # type: ignore[misc]
    for record in [
        facts,
        facts.dependencies[0],
        facts.stage_assignments[0],
        facts.sources["VirtualMachine/app01"],
    ]:
        assert not hasattr(record, "__dict__")
    assert all(isinstance(f.field_path, tuple) for f in facts.dependencies)


def test_result_owns_source_mapping() -> None:
    facts = classify_dependencies(resolve_resources(load_yaml_files([EXAMPLE, STAGES])))
    sources = dict(facts.sources)
    copy = DependencyFacts(facts.dependencies, facts.stage_assignments, sources)
    sources.clear()
    assert copy == facts


def test_empty_index_and_wrong_input_type() -> None:
    facts = classify_dependencies(resolve_resources([]))
    assert facts.dependencies == ()
    assert facts.stage_assignments == ()
    assert dict(facts.sources) == {}
    with pytest.raises(TypeError, match="ResourceIndex"):
        classify_dependencies({})  # type: ignore[arg-type]


def test_self_and_cyclic_references_are_classified_without_graph_checks(tmp_path: Path):
    docs = load_resources(
        tmp_path,
        [
            stage("a", depends_on=["Stage/a", "Stage/b"]),
            stage("b", depends_on=["Stage/a"]),
        ],
    )
    facts = classify_dependencies(resolve_resources(docs))
    assert [
        (f.prerequisite_identity, f.dependent_identity) for f in facts.dependencies
    ] == [
        ("Stage/a", "Stage/a"),
        ("Stage/b", "Stage/a"),
        ("Stage/a", "Stage/b"),
    ]


@pytest.mark.parametrize(
    "path",
    [
        (),
        ("extensions", "platform", "reference"),
        ("metadata", "owner"),
        ("lifecycle", "phases", "provision"),
        ("spec", "disks", 0, "image"),
        ("spec", "provider"),
        ("depends_on",),
        ("depends_on", 0, "extra"),
        ("depends_on", "0"),
        ("depends_on", True),
        ("depends_on", 0.0),
        ("depends_on", -1),
        ("spec", "interfaces", "10", "network"),
        ("spec", "interfaces", False, "network"),
        ("spec", "interfaces", -1, "network"),
        ("spec", "interfaces", 0, "network", "extra"),
        ("lifecycle", None),
        ("depends_on", [0]),
        ["lifecycle", "stage"],
        "lifecycle.stage",
    ],
)
def test_unknown_shapes_fail_explicitly_with_source_context(path: Any) -> None:
    index = resolve_resources(load_yaml_files([EXAMPLE, STAGES]))
    original = index.references[-1]
    unknown = replace(original, field_path=path)
    with pytest.raises(DependencyClassificationError) as exc:
        classify_dependencies(replace(index, references=(*index.references, unknown)))
    error = exc.value
    assert error.code == "unsupported_reference_field"
    assert error.resource_identity == original.resource_identity
    assert error.target_identity == original.target_identity
    assert error.field_path == path
    assert error.source.source_path == original.source.source_path
    assert error.source.document_index == original.source.document_index
    assert (error.source.line, error.source.column) == (
        original.source.line,
        original.source.column,
    )
    assert repr(path) in str(error)
    assert original.resource_identity in str(error)
    assert original.target_identity in str(error)
    assert "document root" in str(error)


def test_vm_spec_paths_on_other_owner_kinds_do_not_gain_implicit_semantics() -> None:
    index = resolve_resources(load_yaml_files([EXAMPLE, STAGES]))
    invalid = replace(index.references[-1], resource_identity="Hypervisor/host01")
    with pytest.raises(DependencyClassificationError):
        classify_dependencies(replace(index, references=(invalid,)))


def test_error_owner_selection_is_deterministic() -> None:
    index = resolve_resources(load_yaml_files([EXAMPLE, STAGES]))
    invalid = [
        replace(ref, field_path=("future", "field"))
        for ref in (index.references[0], index.references[-1])
    ]
    for records in (invalid, list(reversed(invalid))):
        with pytest.raises(DependencyClassificationError) as exc:
            classify_dependencies(replace(index, references=tuple(records)))
        assert exc.value.resource_identity == "Hypervisor/host01"
