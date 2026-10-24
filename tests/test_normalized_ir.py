"""Portable IR determinism, omission policy and immutable snapshot boundaries."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
import yaml

from diatonic.compiler.loader import LoadedDocument, load_yaml_files
from diatonic.compiler.normalize import (
    NormalizationError,
    NormalizedIR,
    normalize_resources,
)
from diatonic.compiler.references import ResourceResolutionError, resolve_resources

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


def document(data: dict[str, Any]) -> LoadedDocument:
    return LoadedDocument(data, Path("input.yml"), 1, 3, 2)


def test_full_pipeline_preserves_resources_links_and_separate_sources() -> None:
    documents = load_yaml_files([EXAMPLE, STAGES])
    index = resolve_resources(documents)
    ir = normalize_resources(index)
    portable = ir.to_dict()
    assert list(ir.resources) == sorted(index.resources)
    assert list(ir.sources) == sorted(index.resources)
    for identity, entry in index.resources.items():
        assert portable["resources"][identity] == entry.resource.model_dump(
            mode="json",
            exclude_unset=True,
        )
        source = ir.sources[identity]
        assert (
            source.source_path,
            source.document_index,
            source.line,
            source.column,
        ) == (
            entry.source.source_path,
            entry.source.document_index,
            entry.source.line,
            entry.source.column,
        )
        assert source is not entry.source
    assert [
        (r.resource_identity, r.field_path, r.target_identity) for r in ir.references
    ] == [
        (r.resource_identity, r.field_path, r.target_identity)
        for r in sorted(index.references, key=lambda r: r.resource_identity)
    ]
    assert set(portable) == {"resources", "references"}
    assert str(EXAMPLE) not in ir.to_json()
    assert json.loads(ir.to_json()) == portable
    assert ir == normalize_resources(index)


def test_missing_stages_are_not_silently_supplied() -> None:
    with pytest.raises(ResourceResolutionError) as exc:
        normalize_resources(resolve_resources(load_yaml_files([EXAMPLE])))
    assert exc.value.diagnostic.reference == "Stage/platform"


def test_portable_output_independent_of_paths_boundaries_and_input_order(
    tmp_path: Path,
):
    documents = load_yaml_files([EXAMPLE, STAGES])
    baseline = normalize_resources(resolve_resources(documents))
    paths = []
    for i, doc in enumerate(reversed(documents)):
        directory = tmp_path / str(i)
        directory.mkdir()
        path = directory / "renamed.yaml"
        path.write_text(yaml.safe_dump(doc.data, sort_keys=True), encoding="utf-8")
        paths.append(path)
    relocated = normalize_resources(resolve_resources(load_yaml_files(paths)))
    assert relocated.to_json() == baseline.to_json()
    assert relocated.to_dict() == baseline.to_dict()
    assert relocated.sources != baseline.sources
    reordered = normalize_resources(
        resolve_resources(load_yaml_files(list(reversed(paths))))
    )
    assert reordered.to_json() == baseline.to_json()
    assert all(s.document_index == 1 for s in relocated.sources.values())


def test_identity_order_preserves_case_and_same_names_across_kinds() -> None:
    index = resolve_resources(
        [document(vm("same")), document(stage("same")), document(stage("Same"))]
    )
    assert list(normalize_resources(index).resources) == [
        "Stage/Same",
        "Stage/same",
        "VirtualMachine/same",
    ]


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"lifecycle": None},
        {"lifecycle": {}},
        {
            "lifecycle": {
                "prevent_destroy": False,
                "desired_state": None,
                "phases": {"observe": None},
            }
        },
        {
            "depends_on": [],
            "extensions": {},
            "metadata": {
                "name": "s",
                "description": None,
                "labels": {},
                "annotations": {},
            },
        },
    ],
)
def test_omitted_defaults_explicit_null_false_empty_and_zero(fields: dict[str, Any]):
    data = stage("s", **fields)
    ir = normalize_resources(resolve_resources([document(data)]))
    assert ir.resources["Stage/s"].to_dict() == data
    assert ir.resources["Stage/s"].to_dict()["spec"]["order"] == 0


def test_minimal_vm_omits_implicit_optional_sections() -> None:
    data = vm()
    ir = normalize_resources(resolve_resources([document(data)]))
    assert ir.resources["VirtualMachine/app"].to_dict() == data
    data["spec"].update(placement=None, image=None, disks=[], interfaces=[])
    explicit = normalize_resources(resolve_resources([document(data)]))
    assert explicit.resources["VirtualMachine/app"].to_dict() == data
    assert ir.to_json() != explicit.to_json()


def test_nested_extensions_mapping_order_and_scalar_values() -> None:
    values = {"z": [{"b": None, "a": False}, 0, "żółw"], "a": {"y": 1.25, "x": []}}
    data = stage("s", extensions={"example_platform": values})
    ir = normalize_resources(resolve_resources([document(data)]))
    assert ir.resources["Stage/s"].to_dict() == data
    other = stage(
        "s",
        extensions={
            "example_platform": {
                "a": {"x": [], "y": 1.25},
                "z": [{"a": False, "b": None}, 0, "żółw"],
            }
        },
    )
    assert ir == normalize_resources(resolve_resources([document(other)]))
    assert "żółw" in ir.to_json()
    assert ir.to_json() == json.dumps(
        ir.to_dict(),
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )
    exported = ir.resources["Stage/s"].to_dict()["extensions"]["example_platform"]
    assert list(exported) == ["a", "z"]
    assert list(exported["z"][0]) == ["a", "b"]


def test_meaningful_list_order_and_numeric_reference_indices() -> None:
    network = {
        "api_version": "iac/v0alpha1",
        "kind": "Network",
        "metadata": {"name": "net"},
        "spec": {
            "vlan_id": 10,
            "ipv4": {"cidr": "192.0.2.0/24", "gateway": "192.0.2.1"},
        },
    }
    resource = vm(
        depends_on=["Stage/z", "Stage/a", "Stage/z"], lifecycle={"stage": "z"}
    )
    resource["spec"].update(
        disks=[{"name": "z", "size_gib": 2}, {"name": "a", "size_gib": 1}],
        interfaces=[{"name": f"nic{i}", "network": "Network/net"} for i in range(12)],
    )
    docs = [
        document(resource),
        document(stage("z", depends_on=["Stage/a"])),
        document(stage("a")),
        document(network),
    ]
    ir = normalize_resources(resolve_resources(docs))
    assert [ref.resource_identity for ref in ir.references][:2] == [
        "Stage/z",
        "VirtualMachine/app",
    ]
    refs = [r for r in ir.references if r.resource_identity == "VirtualMachine/app"]
    assert [r.field_path for r in refs] == [
        ("depends_on", 0),
        ("depends_on", 1),
        ("depends_on", 2),
        ("lifecycle", "stage"),
        *[("spec", "interfaces", i, "network") for i in range(12)],
    ]
    assert [ref.target_identity for ref in refs[:4]] == [
        "Stage/z",
        "Stage/a",
        "Stage/z",
        "Stage/z",
    ]
    assert ir.resources["VirtualMachine/app"].to_dict() == resource
    assert ir.to_dict()["references"][-1]["field_path"] == [
        "spec",
        "interfaces",
        11,
        "network",
    ]


def test_input_mutations_cannot_change_an_existing_ir() -> None:
    data = vm(extensions={"platform": {"nested": [{"enabled": True}]}})
    docs = [document(data)]
    index = resolve_resources(docs)
    before_models = {
        key: entry.resource.model_dump(mode="json", exclude_unset=True)
        for key, entry in index.resources.items()
    }
    original = deepcopy(docs)
    ir = normalize_resources(index)
    expected = ir.to_json()
    assert docs == original
    assert {
        key: entry.resource.model_dump(mode="json", exclude_unset=True)
        for key, entry in index.resources.items()
    } == before_models
    data["extensions"]["platform"]["nested"][0]["enabled"] = False
    parsed = index.resources["VirtualMachine/app"].resource
    parsed.extensions["platform"]["nested"].append("changed")
    parsed.metadata.name = "changed"
    parsed.spec.cpu.cores = 99
    assert ir.to_json() == expected


def test_repeated_exports_are_detached_at_every_depth() -> None:
    data = stage(
        "s",
        depends_on=["Stage/s"],
        extensions={"platform": {"nested": [{"enabled": True}]}},
    )
    ir = normalize_resources(resolve_resources([document(data)]))
    expected = ir.to_json()
    first = ir.to_dict()
    second = ir.to_dict()
    first["resources"]["Stage/s"]["extensions"]["platform"]["nested"][0]["enabled"] = (
        False
    )
    first["references"][0]["field_path"].append("changed")
    first["resources"].clear()
    individual = ir.resources["Stage/s"].to_dict()
    individual["depends_on"].append("Stage/other")
    assert second == ir.to_dict()
    assert ir.to_json() == expected


def test_ir_exposes_only_frozen_records_and_read_only_containers() -> None:
    ir = normalize_resources(
        resolve_resources([document(stage("s", depends_on=["Stage/s"]))])
    )
    with pytest.raises(TypeError):
        ir.resources["Stage/other"] = ir.resources["Stage/s"]  # type: ignore[index]
    with pytest.raises(TypeError):
        ir.sources["Stage/s"] = ir.sources["Stage/s"]  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        ir.references = ()  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ir.resources["Stage/s"]._data_json = "{}"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ir.references[0].target_identity = "Stage/other"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        ir.sources["Stage/s"].line = 999  # type: ignore[misc]
    assert isinstance(ir.references[0].field_path, tuple)
    for record in [
        ir,
        ir.resources["Stage/s"],
        ir.references[0],
        ir.sources["Stage/s"],
    ]:
        assert not hasattr(record, "__dict__")


def test_ir_owns_backing_mappings() -> None:
    ir = normalize_resources(resolve_resources([document(stage("s"))]))
    resources, sources = dict(ir.resources), dict(ir.sources)
    copied = NormalizedIR(resources, ir.references, sources)
    resources.clear()
    sources.clear()
    assert copied == ir


@pytest.mark.parametrize("field", ["name", "kind"])
def test_mutated_identity_is_rejected_with_source(field: str) -> None:
    index = resolve_resources([document(stage("s"))])
    entry = index.resources["Stage/s"]
    if field == "name":
        entry.resource.metadata.name = "changed"
    else:
        entry.resource.kind = "Image"
    with pytest.raises(NormalizationError) as exc:
        normalize_resources(index)
    assert exc.value.code == "identity_mismatch"
    assert exc.value.indexed_identity == "Stage/s"
    assert exc.value.resource_identity == entry.resource.identity
    assert exc.value.source == entry.source


def test_identity_failure_order_is_canonical() -> None:
    index = resolve_resources([document(stage("z")), document(stage("a"))])
    for entry in index.resources.values():
        entry.resource.metadata.name += "changed"
    with pytest.raises(NormalizationError) as exc:
        normalize_resources(index)
    assert exc.value.indexed_identity == "Stage/a"


def test_empty_index_and_wrong_input_type() -> None:
    ir = normalize_resources(resolve_resources([]))
    assert ir.to_dict() == {"resources": {}, "references": []}
    assert ir.to_json() == '{"references":[],"resources":{}}'
    assert dict(ir.sources) == {}
    with pytest.raises(TypeError, match="ResourceIndex"):
        normalize_resources({})  # type: ignore[arg-type]


def test_nonfinite_mutated_extension_value_is_not_silently_serialized() -> None:
    index = resolve_resources([document(stage("s", extensions={"platform": {"n": 1}}))])
    index.resources["Stage/s"].resource.extensions["platform"]["n"] = float("inf")
    with pytest.raises(ValueError, match="Out of range float"):
        normalize_resources(index)
