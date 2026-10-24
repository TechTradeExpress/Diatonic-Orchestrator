"""M1.5 validation/index handoff, provenance and declared reference resolution."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from diatonic.compiler.loader import LoadedDocument, load_yaml_files
from diatonic.compiler.references import (
    ResourceResolutionError,
    SourceLocation,
    resolve_resources,
)
from diatonic.model import parse_resource

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/infrastructure/resources.yml"
STAGES = ROOT / "tests/fixtures/reference-stages.yml"


def data(kind: str, name: str, **overrides: Any) -> dict[str, Any]:
    specs = {
        "Stage": {"order": 10},
        "VirtualMachine": {"cpu": {"cores": 1}, "memory": {"mib": 512}},
        "Network": {
            "vlan_id": 10,
            "ipv4": {"cidr": "192.0.2.0/24", "gateway": "192.0.2.1"},
        },
        "Hypervisor": {"management": {"address": "192.0.2.10"}},
        "Image": {
            "os": {
                "family": "linux",
                "distribution": "debian",
                "version": "13",
                "architecture": "amd64",
            }
        },
    }
    result = {
        "api_version": "iac/v0alpha1",
        "kind": kind,
        "metadata": {"name": name},
        "spec": specs.get(kind, {}),
    }
    result.update(overrides)
    return result


def loaded(
    resource: dict[str, Any],
    path: str = "resources.yml",
    index: int = 1,
    line: int = 3,
    column: int = 1,
) -> LoadedDocument:
    return LoadedDocument(resource, Path(path), index, line, column)


def failure(documents: list[LoadedDocument]):
    with pytest.raises(ResourceResolutionError) as exc:
        resolve_resources(documents)
    return exc.value.diagnostic


def test_full_example_with_explicit_stages_and_provenance() -> None:
    documents = load_yaml_files([EXAMPLE, STAGES])
    before = deepcopy(documents)
    result = resolve_resources(documents)
    assert list(result.resources) == [
        "Network/servers",
        "Hypervisor/host01",
        "Image/debian13",
        "VirtualMachine/app01",
        "Stage/platform",
        "Stage/workloads",
    ]
    for document, entry in zip(documents, result.resources.values(), strict=True):
        assert entry.source == SourceLocation(
            document.source_path,
            document.document_index,
            document.line,
            document.column,
        )
        assert entry.resource == parse_resource(document.data)
        assert entry.resource.model_dump(exclude_unset=True) == document.data
    assert [
        (ref.resource_identity, ref.field_path, ref.target_identity)
        for ref in result.references
    ] == [
        ("Hypervisor/host01", ("lifecycle", "stage"), "Stage/platform"),
        ("VirtualMachine/app01", ("lifecycle", "stage"), "Stage/workloads"),
        ("VirtualMachine/app01", ("spec", "placement", "target"), "Hypervisor/host01"),
        (
            "VirtualMachine/app01",
            ("spec", "interfaces", 0, "network"),
            "Network/servers",
        ),
        ("VirtualMachine/app01", ("spec", "image", "ref"), "Image/debian13"),
    ]
    for ref in result.references:
        assert ref.target_identity in result.resources
        assert ref.source == result.resources[ref.resource_identity].source
    assert documents == before
    assert result == resolve_resources(iter(documents))
    with pytest.raises(TypeError):
        result.resources["Stage/other"] = result.resources["Stage/platform"]  # type: ignore[index]


@pytest.mark.parametrize("missing", ["platform", "workloads"])
def test_example_missing_stage_is_reported_without_implicit_declarations(missing: str):
    documents = load_yaml_files([EXAMPLE, STAGES])
    documents = [
        doc
        for doc in documents
        if doc.data.get("kind") != "Stage" or doc.data["metadata"] != {"name": missing}
    ]
    diagnostic = failure(documents)
    assert diagnostic.code == "missing_reference"
    assert diagnostic.reference == f"Stage/{missing}"
    assert diagnostic.field_path == ("lifecycle", "stage")
    assert diagnostic.source.source_path == EXAMPLE


def test_unaugmented_example_reports_first_missing_stage() -> None:
    diagnostic = failure(load_yaml_files([EXAMPLE]))
    assert diagnostic.reference == "Stage/platform"
    assert diagnostic.resource_identity == "Hypervisor/host01"
    assert diagnostic.source.document_index == 2


def test_forward_cross_file_references_and_multiple_interfaces() -> None:
    vm = data(
        "VirtualMachine",
        "app",
        depends_on=["Image/os", "Stage/workloads"],
        lifecycle={"stage": "workloads"},
    )
    vm["spec"].update(
        placement={"target": "Hypervisor/host"},
        image={"ref": "Image/os"},
        interfaces=[
            {"name": "one", "network": "Network/one"},
            {"name": "two", "network": "Network/two"},
            {"name": "three", "network": "Network/one"},
        ],
    )
    documents = [
        loaded(vm, "first.yml"),
        loaded(data("Network", "one"), "second.yml", 1),
        loaded(data("Network", "two"), "second.yml", 2),
        loaded(data("Image", "os"), "second.yml", 3),
        loaded(data("Stage", "workloads"), "second.yml", 4),
        loaded(data("Hypervisor", "host"), "second.yml", 5),
    ]
    result = resolve_resources(documents)
    assert [ref.target_identity for ref in result.references] == [
        "Image/os",
        "Stage/workloads",
        "Stage/workloads",
        "Hypervisor/host",
        "Network/one",
        "Network/two",
        "Network/one",
        "Image/os",
    ]
    assert [ref.field_path for ref in result.references] == [
        ("depends_on", 0),
        ("depends_on", 1),
        ("lifecycle", "stage"),
        ("spec", "placement", "target"),
        ("spec", "interfaces", 0, "network"),
        ("spec", "interfaces", 1, "network"),
        ("spec", "interfaces", 2, "network"),
        ("spec", "image", "ref"),
    ]


def test_same_names_different_kinds_and_case_sensitive_identity() -> None:
    documents = [
        loaded(data(kind, "shared"))
        for kind in ("Stage", "Network", "Image", "Hypervisor", "VirtualMachine")
    ]
    documents.append(loaded(data("Stage", "Shared")))
    result = resolve_resources(documents)
    assert len(result.resources) == 6
    assert result.references == ()


@pytest.mark.parametrize(
    "kind", ["Stage", "Network", "Image", "Hypervisor", "VirtualMachine"]
)
@pytest.mark.parametrize("same_file", [True, False])
def test_duplicate_identities_report_both_origins(kind: str, same_file: bool) -> None:
    first = loaded(data(kind, "same"), "first.yml", 1, 4, 2)
    second = loaded(
        data(kind, "same"),
        "first.yml" if same_file else "second.yml",
        2 if same_file else 1,
        10,
        3,
    )
    diagnostic = failure([first, second])
    assert diagnostic.code == "duplicate_identity"
    assert diagnostic.resource_identity == f"{kind}/same"
    assert diagnostic.field_path == ("metadata", "name")
    assert diagnostic.related_source == SourceLocation(first.source_path, 1, 4, 2)
    assert diagnostic.source == SourceLocation(
        second.source_path, second.document_index, 10, 3
    )
    with pytest.raises(ResourceResolutionError) as exc:
        resolve_resources([first, second])
    assert str(diagnostic.related_source) in str(exc.value)
    assert str(diagnostic.source) in str(exc.value)


def test_duplicate_in_yaml_stream_and_repeated_file_path(tmp_path: Path) -> None:
    text = (
        "api_version: iac/v0alpha1\nkind: Stage\n"
        "metadata: {name: a}\nspec: {order: 1}\n"
    )
    path = tmp_path / "stages.yml"
    path.write_text(text + "---\n" + text, encoding="utf-8")
    diagnostic = failure(load_yaml_files([path]))
    assert diagnostic.related_source is not None
    assert diagnostic.related_source.document_index == 1
    assert diagnostic.source.document_index == 2
    path.write_text(text, encoding="utf-8")
    diagnostic = failure(load_yaml_files([path, path]))
    assert diagnostic.code == "duplicate_identity"
    assert diagnostic.related_source == diagnostic.source


@pytest.mark.parametrize(
    ("section", "field_path", "target"),
    [
        ({"depends_on": ["Network/missing"]}, ("depends_on", 0), "Network/missing"),
        ({"lifecycle": {"stage": "missing"}}, ("lifecycle", "stage"), "Stage/missing"),
        (
            {"placement": {"target": "Hypervisor/missing"}},
            ("spec", "placement", "target"),
            "Hypervisor/missing",
        ),
        (
            {"interfaces": [{"name": "one", "network": "Network/missing"}]},
            ("spec", "interfaces", 0, "network"),
            "Network/missing",
        ),
        (
            {"image": {"ref": "Image/missing"}},
            ("spec", "image", "ref"),
            "Image/missing",
        ),
    ],
)
def test_missing_references_have_owner_path_target_and_root_source(
    section: dict[str, Any],
    field_path: tuple[str | int, ...],
    target: str,
) -> None:
    vm = data("VirtualMachine", "app")
    if field_path[0] == "spec":
        vm["spec"].update(section)
    else:
        vm.update(section)
    document = loaded(vm, "vm.yml", 3, 12, 5)
    before = deepcopy(document)
    diagnostic = failure([document])
    assert diagnostic.code == "missing_reference"
    assert diagnostic.resource_identity == "VirtualMachine/app"
    assert diagnostic.reference == target
    assert diagnostic.field_path == field_path
    assert diagnostic.source == SourceLocation(Path("vm.yml"), 3, 12, 5)
    assert document == before


def test_missing_depends_on_unsupported_kind_is_not_added_automatically() -> None:
    diagnostic = failure([loaded(data("Stage", "a", depends_on=["Service/dns"]))])
    assert diagnostic.code == "missing_reference"
    assert diagnostic.reference == "Service/dns"


@pytest.mark.parametrize(
    ("field", "value", "path"),
    [
        ("placement", {"target": "Network/shared"}, ("spec", "placement", "target")),
        (
            "interfaces",
            [{"name": "one", "network": "Image/shared"}],
            ("spec", "interfaces", 0, "network"),
        ),
        ("image", {"ref": "Hypervisor/shared"}, ("spec", "image", "ref")),
    ],
)
def test_wrong_kind_references_are_schema_errors(field: str, value: Any, path: tuple):
    vm = data("VirtualMachine", "app")
    vm["spec"][field] = value
    diagnostic = failure([loaded(vm)])
    assert diagnostic.code == "invalid_resource"
    assert diagnostic.schema_error_code == "value_error"
    assert diagnostic.field_path == path
    assert diagnostic.resource_identity == "VirtualMachine/app"


@pytest.mark.parametrize(
    "field", ["placement", "interfaces", "image", "stage", "depends_on"]
)
def test_same_named_other_kind_never_substitutes_for_target(field: str) -> None:
    vm = data("VirtualMachine", "app")
    values = {
        "placement": {"target": "Hypervisor/shared"},
        "interfaces": [{"name": "one", "network": "Network/shared"}],
        "image": {"ref": "Image/shared"},
    }
    if field in values:
        vm["spec"][field] = values[field]
    elif field == "stage":
        vm["lifecycle"] = {"stage": "shared"}
    else:
        vm["depends_on"] = ["Network/shared"]
    other = loaded(data("VirtualMachine", "shared"))
    diagnostic = failure([loaded(vm), other])
    assert diagnostic.code == "missing_reference"
    assert diagnostic.reference != "VirtualMachine/shared"


@pytest.mark.parametrize(
    ("overrides", "path", "schema_code", "identity"),
    [
        ({"kind": "Unknown"}, ("kind",), "union_tag_invalid", "Unknown/app"),
        (
            {"api_version": "iac/v0alpha2"},
            ("api_version",),
            "literal_error",
            "VirtualMachine/app",
        ),
        (
            {"spec": {"cpu": {"cores": 0}, "memory": {"mib": 1}}},
            ("spec", "cpu", "cores"),
            "greater_than",
            "VirtualMachine/app",
        ),
        ({"metadata": {"name": "bad/name"}}, ("metadata", "name"), "value_error", None),
        ({"metadata": {}}, ("metadata", "name"), "missing", None),
        ({"kind": None}, ("kind",), "union_tag_invalid", None),
        ({"spec": []}, ("spec",), "model_type", "VirtualMachine/app"),
        (
            {"depends_on": ["Network"]},
            ("depends_on", 0),
            "value_error",
            "VirtualMachine/app",
        ),
        (
            {"lifecycle": {"stage": "Stage/workloads"}},
            ("lifecycle", "stage"),
            "value_error",
            "VirtualMachine/app",
        ),
    ],
)
def test_invalid_resources_are_wrapped_with_schema_detail_and_provenance(
    overrides: dict[str, Any],
    path: tuple,
    schema_code: str,
    identity: str | None,
) -> None:
    resource = data("VirtualMachine", "app")
    resource.update(overrides)
    document = loaded(resource, "bad.yml", 4, 8, 2)
    before = deepcopy(document)
    diagnostic = failure([document])
    assert diagnostic.code == "invalid_resource"
    assert diagnostic.schema_error_code == schema_code
    assert diagnostic.field_path == path
    assert diagnostic.resource_identity == identity
    assert diagnostic.source == SourceLocation(Path("bad.yml"), 4, 8, 2)
    assert diagnostic.message
    assert document == before


def test_optional_fields_and_empty_input_generate_no_links() -> None:
    result = resolve_resources([loaded(data("VirtualMachine", "minimal"))])
    assert result.references == ()
    assert list(result.resources) == ["VirtualMachine/minimal"]
    assert dict(resolve_resources([]).resources) == {}


def test_missing_kind_produces_controlled_discriminator_error() -> None:
    resource = data("Stage", "a")
    del resource["kind"]
    diagnostic = failure([loaded(resource)])
    assert diagnostic.code == "invalid_resource"
    assert diagnostic.schema_error_code == "union_tag_not_found"
    assert diagnostic.field_path == ("kind",)
    assert diagnostic.resource_identity is None


def test_input_extension_containers_and_serialization_are_preserved() -> None:
    resource = data(
        "VirtualMachine",
        "app",
        extensions={"platform": {"nested": [{"enabled": True}]}},
    )
    document = loaded(resource)
    before = deepcopy(document)
    result = resolve_resources([document])
    parsed = result.resources["VirtualMachine/app"].resource
    assert parsed.model_dump(exclude_unset=True) == resource
    parsed.extensions["platform"]["nested"].append("changed")
    assert document == before


def test_indexing_finishes_before_resolution_and_failure_is_repeatable() -> None:
    missing = loaded(data("Stage", "a", depends_on=["Stage/missing"]))
    invalid = loaded(data("Stage", "b", api_version="invalid"), "invalid.yml")
    documents = [missing, invalid]
    first = failure(documents)
    assert first.code == "invalid_resource"
    assert first.resource_identity == "Stage/b"
    assert first == failure(documents)
    duplicate = replace(missing, source_path=Path("duplicate.yml"))
    assert failure([missing, duplicate]).code == "duplicate_identity"


def test_fail_fast_document_and_reference_order_are_explicit() -> None:
    first = data(
        "Stage",
        "first",
        depends_on=["Image/two", "Stage/one"],
        lifecycle={"stage": "absent"},
    )
    second = data("Stage", "second", depends_on=["Network/three"])
    documents = [loaded(first), loaded(second)]
    assert failure(documents).reference == "Image/two"
    assert failure(list(reversed(documents))).reference == "Network/three"
    first["depends_on"] = []
    assert failure(documents).reference == "Stage/absent"


def test_schema_failure_reports_first_pydantic_field_error() -> None:
    vm = data("VirtualMachine", "app")
    vm["spec"] = {"cpu": {"cores": 0}, "memory": {"mib": 0}}
    assert failure([loaded(vm)]).field_path == ("spec", "cpu", "cores")


def test_self_and_cyclic_links_resolve_without_graph_semantics() -> None:
    result = resolve_resources(
        [
            loaded(data("Stage", "a", depends_on=["Stage/a", "Stage/b"])),
            loaded(data("Stage", "b", depends_on=["Stage/a"])),
        ]
    )
    assert [ref.target_identity for ref in result.references] == [
        "Stage/a",
        "Stage/b",
        "Stage/a",
    ]
