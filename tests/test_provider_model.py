"""Portable Provider declarations integrate without driver or config interpretation."""

import json
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError
from typer.testing import CliRunner

from diatonic.cli import app
from diatonic.compiler.dependencies import classify_dependencies
from diatonic.compiler.graph import build_dependency_graph
from diatonic.compiler.loader import YamlLoadError, load_yaml_files
from diatonic.compiler.normalize import normalize_resources
from diatonic.compiler.references import ResourceResolutionError, resolve_resources
from diatonic.compiler.semantics import validate_ipv4_semantics
from diatonic.compiler.stages import analyze_stage_order
from diatonic.model import (
    Provider,
    ProviderSpec,
    Resource,
    ResourceBase,
    parse_resource,
)

runner = CliRunner()


def provider(name: str = "primary", **fields: Any) -> dict[str, Any]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Provider",
        "metadata": {"name": name},
        "spec": {"driver": "example.unregistered", "config": {}},
        **fields,
    }


def stage(name: str = "platform", order: int = 20) -> dict[str, Any]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": name},
        "spec": {"order": order},
    }


def opaque_config() -> dict[str, Any]:
    return {
        "endpoint": "https://provider.invalid",
        "credentials": {"token": {"secret_ref": "example/token"}},
        "future": [
            None,
            True,
            False,
            -7,
            2**64,
            0.125,
            "13",
            "λ",
            {"list": [[], {}, {"enabled": True}]},
        ],
        "uninterpreted": {
            "ref": "Provider/missing",
            "target": "Hypervisor/missing",
            "network": "Network/missing",
            "stage": "missing",
            "expression": "${UNRESOLVED_EXAMPLE}",
        },
    }


def write(tmp_path: Path, resources, filename: str = "input.yml") -> Path:
    path = tmp_path / filename
    path.write_text(yaml.safe_dump_all(resources, sort_keys=False), encoding="utf-8")
    return path


def compile_paths(paths):
    documents = load_yaml_files(paths)
    index = resolve_resources(documents)
    validate_ipv4_semantics(index)
    ir = normalize_resources(index)
    facts = classify_dependencies(index)
    graph = build_dependency_graph(index, facts)
    analysis = analyze_stage_order(index, graph)
    return documents, index, ir, facts, graph, analysis


def test_direct_model_union_dispatch_and_identity():
    data = provider(spec={"driver": "terraform.proxmox", "config": opaque_config()})
    before = deepcopy(data)
    parsed = parse_resource(data)
    assert type(parsed) is Provider
    assert isinstance(parsed, ResourceBase)
    assert type(parsed.spec) is ProviderSpec
    assert parsed.identity == "Provider/primary"
    assert parsed.spec.driver == "terraform.proxmox"
    assert parsed == Provider.model_validate(data)
    assert parsed == Provider.model_validate_json(json.dumps(data))
    assert parsed == TypeAdapter(Resource).validate_python(data)
    assert parsed.model_dump(mode="json", exclude_unset=True) == data == before
    assert parsed.lifecycle is None
    assert parsed.depends_on == []
    assert parsed.spec.config["future"][1] is True
    assert type(parsed.spec.config["future"][3]) is int
    assert type(parsed.spec.config["future"][5]) is float
    assert parsed.spec.config["future"][6] == "13"


def test_schema_requiredness_exports_and_supported_discriminators():
    schema = ProviderSpec.model_json_schema()
    assert set(schema["required"]) == {"driver", "config"}
    assert schema["additionalProperties"] is False
    assert "default" not in schema["properties"]["config"]
    mapping = TypeAdapter(Resource).json_schema()["discriminator"]["mapping"]
    assert set(mapping) == {
        "Stage",
        "Network",
        "Hypervisor",
        "Image",
        "VirtualMachine",
        "Provider",
        "ProviderBinding",
    }
    assert "Project" not in mapping


@pytest.mark.parametrize(
    "path",
    [
        ("api_version",),
        ("kind",),
        ("metadata",),
        ("metadata", "name"),
        ("spec",),
        ("spec", "driver"),
        ("spec", "config"),
    ],
)
def test_missing_required_fields(path):
    data = provider()
    parent = data
    for segment in path[:-1]:
        parent = parent[segment]
    del parent[path[-1]]
    for parser in (Provider.model_validate, parse_resource):
        with pytest.raises(ValidationError) as caught:
            parser(data)
        assert caught.value.errors()[0]["type"] in {"missing", "union_tag_not_found"}


@pytest.mark.parametrize(
    "driver",
    [
        "terraform.proxmox",
        "native.proxmox",
        "future-driver:v42",
        "custom",
        "DRIVER",
        "λ",
    ],
)
def test_driver_ids_are_opaque_single_segments_without_allowlist(driver):
    spec = ProviderSpec(driver=driver, config={})
    assert spec.driver == driver
    assert spec.config == {}
    assert (
        parse_resource(provider(spec=spec.model_dump())).identity == "Provider/primary"
    )


@pytest.mark.parametrize(
    "driver",
    [
        "",
        " ",
        "a b",
        "a\tb",
        "a\nb",
        "name/part",
        "Provider/primary",
        1,
        1.5,
        True,
        None,
        [],
        {},
        b"driver",
    ],
)
def test_invalid_driver_names_and_coercion_are_rejected(driver):
    with pytest.raises(ValidationError) as caught:
        ProviderSpec(driver=driver, config={})
    assert caught.value.errors()[0]["loc"] == ("driver",)


@pytest.mark.parametrize("value", [None, [], (), "", 1, 1.5, True, b"config"])
def test_config_must_be_explicit_mapping(value):
    with pytest.raises(ValidationError) as caught:
        ProviderSpec(driver="example.driver", config=value)
    assert caught.value.errors()[0]["loc"] == ("config",)


@pytest.mark.parametrize("spec", [None, [], "invalid", 1, True])
def test_spec_must_be_mapping(spec):
    with pytest.raises(ValidationError):
        parse_resource(provider(spec=spec))


@pytest.mark.parametrize(
    "value",
    [
        object(),
        b"not-json",
        {1, 2},
        (1, 2),
        Decimal("1.5"),
        date(2026, 1, 1),
        datetime(2026, 1, 1),
        Path("example.yml"),
        UUID(int=0),
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
@pytest.mark.parametrize("nested", [False, True])
def test_non_json_objects_and_nonfinite_values_are_rejected_at_any_depth(value, nested):
    config = {"bad": [{"nested": value}]} if nested else {"bad": value}
    with pytest.raises(ValidationError):
        ProviderSpec(driver="example.driver", config=config)


@pytest.mark.parametrize("key", [1, 1.5, True, None, b"key", ("key",)])
@pytest.mark.parametrize("nested", [False, True])
def test_non_string_mapping_keys_are_not_coerced(key, nested):
    config = {"outer": [{key: "value"}]} if nested else {key: "value"}
    with pytest.raises(ValidationError):
        ProviderSpec(driver="example.driver", config=config)


@pytest.mark.parametrize(
    "kind", ["provider", "ProviderBinding", "VirtualMachine", "Unknown"]
)
def test_concrete_provider_requires_exact_kind(kind):
    with pytest.raises(ValidationError):
        Provider.model_validate(provider(kind=kind))
    if kind not in ("VirtualMachine", "ProviderBinding"):
        with pytest.raises(ValidationError) as caught:
            parse_resource(provider(kind=kind))
        assert caught.value.errors()[0]["type"] == "union_tag_invalid"


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_version", "iac/v0alpha2"),
        ("api_version", None),
        ("metadata", {"name": 7}),
        ("metadata", {"name": "bad/name"}),
        ("metadata", {"name": "primary", "labels": {"site": 1}}),
        ("lifecycle", {"prevent_destroy": "true"}),
        ("lifecycle", {"phases": {"observe": "unknown"}}),
        ("depends_on", ["not-a-reference"]),
        ("extensions", {"platform": {"bad": object()}}),
        ("unknown", True),
    ],
)
def test_shared_envelope_rejections_are_unchanged(field, value):
    with pytest.raises(ValidationError):
        parse_resource(provider(**{field: value}))


def test_unknown_spec_fields_fail_but_opaque_config_fields_survive():
    with pytest.raises(ValidationError) as caught:
        ProviderSpec(driver="example.driver", config={}, capabilities=["example"])
    assert caught.value.errors()[0]["type"] == "extra_forbidden"
    config = {
        "capabilities": ["opaque"],
        "arbitrary": {"unknown": 1},
        "secret_ref": None,
    }
    assert ProviderSpec(driver="example.driver", config=config).config == config


def test_shared_fields_omission_null_and_no_lifecycle_defaults():
    data = provider(
        metadata={
            "name": "primary",
            "description": "Example instance",
            "labels": {"site": "lab"},
            "annotations": {"owner": "example"},
        },
        lifecycle={
            "stage": "platform",
            "desired_state": "absent",
            "phases": {"observe": "external", "configure": "disabled"},
            "prevent_destroy": True,
        },
        depends_on=["Stage/platform"],
        extensions={"platform": {"feature": True, "options": [1, None, "value"]}},
    )
    parsed = parse_resource(data)
    assert parsed.model_dump(exclude_unset=True) == data
    assert parsed.lifecycle.phases.provision is None
    omitted = parse_resource(provider()).model_dump(exclude_unset=True)
    explicit = parse_resource(provider(lifecycle=None)).model_dump(exclude_unset=True)
    assert "lifecycle" not in omitted
    assert explicit["lifecycle"] is None
    assert omitted["spec"]["config"] == {}


def test_model_instances_have_independent_nested_config_containers():
    config = opaque_config()
    first = ProviderSpec(driver="same.driver", config=config)
    second = ProviderSpec(driver="same.driver", config=config)
    assert first.config is not config and second.config is not first.config
    first.config["future"][8]["list"].append("changed")
    first.config["credentials"]["token"]["secret_ref"] = "changed/ref"
    assert second.config == config == opaque_config()
    config["future"].clear()
    assert second.config == opaque_config()


def test_provider_yaml_roundtrip_isolated_graph_and_exact_secret_preservation(tmp_path):
    data = provider(spec={"driver": "native.unregistered", "config": opaque_config()})
    path = write(tmp_path, [data])
    docs, index, ir, facts, graph, analysis = compile_paths([path])
    assert docs[0].data == data
    assert (
        index.resources["Provider/primary"].resource.model_dump(exclude_unset=True)
        == data
    )
    assert ir.to_dict()["resources"]["Provider/primary"] == data
    assert json.loads(ir.to_json())["resources"]["Provider/primary"] == data
    assert index.references == facts.dependencies == facts.stage_assignments == ()
    assert graph.vertices == analysis.order == ("Provider/primary",)
    assert graph.edges == () and graph.successors["Provider/primary"] == ()
    assert dict(analysis.assignments) == {}
    for source in (
        index.resources["Provider/primary"].source,
        ir.sources["Provider/primary"],
        graph.sources["Provider/primary"],
    ):
        assert (
            source.source_path,
            source.document_index,
            source.line,
            source.column,
        ) == (path, 1, 1, 1)


def test_duplicate_identity_reports_both_document_roots(tmp_path):
    first = write(tmp_path, [provider()], "first.yml")
    second = tmp_path / "second.yml"
    second.write_text("# example\n" + yaml.safe_dump(provider()), encoding="utf-8")
    for paths, expected_document in [([first, second], 1), ([first, first], 1)]:
        with pytest.raises(ResourceResolutionError) as caught:
            resolve_resources(load_yaml_files(paths))
        diagnostic = caught.value.diagnostic
        assert diagnostic.code == "duplicate_identity"
        assert diagnostic.resource_identity == "Provider/primary"
        assert diagnostic.related_source.source_path == first
        assert diagnostic.related_source.document_index == 1
        assert diagnostic.source.source_path == paths[1]
        assert diagnostic.source.document_index == expected_document
        assert diagnostic.source.line == (2 if paths[1] == second else 1)
    stream = write(tmp_path, [provider(), provider()], "stream.yml")
    with pytest.raises(ResourceResolutionError) as caught:
        resolve_resources(load_yaml_files([stream]))
    assert caught.value.diagnostic.source.document_index == 2
    assert caught.value.diagnostic.related_source.document_index == 1


def test_forward_cross_file_references_shared_drivers_and_same_names(tmp_path):
    first = write(
        tmp_path,
        [
            provider(
                "secondary",
                depends_on=["Provider/primary"],
                lifecycle={"stage": "platform"},
            ),
            {
                "api_version": "iac/v0alpha1",
                "kind": "VirtualMachine",
                "metadata": {"name": "app"},
                "spec": {"cpu": {"cores": 1}, "memory": {"mib": 1}},
                "depends_on": ["Provider/secondary"],
            },
        ],
        "first.yml",
    )
    second = write(tmp_path, [provider(), stage("primary", -10), stage()], "second.yml")
    docs, index, ir, facts, graph, analysis = compile_paths([first, second])
    assert (
        index.resources["Provider/primary"].resource.spec.driver
        == index.resources["Provider/secondary"].resource.spec.driver
    )
    assert "Stage/primary" in index.resources and "Provider/primary" in index.resources
    assert [
        (r.resource_identity, r.field_path, r.target_identity) for r in index.references
    ] == [
        ("Provider/secondary", ("depends_on", 0), "Provider/primary"),
        ("Provider/secondary", ("lifecycle", "stage"), "Stage/platform"),
        ("VirtualMachine/app", ("depends_on", 0), "Provider/secondary"),
    ]
    assert [(e.prerequisite_identity, e.dependent_identity) for e in graph.edges] == [
        ("Provider/primary", "Provider/secondary"),
        ("Provider/secondary", "VirtualMachine/app"),
    ]
    assert all(f.classification == "explicit" for f in facts.dependencies)
    assert len(facts.stage_assignments) == 1
    assert analysis.assignments["Provider/secondary"].order == 20
    assert (
        analysis.order.index("Provider/primary")
        < analysis.order.index("Provider/secondary")
        < analysis.order.index("VirtualMachine/app")
    )
    assert index.references[0].source.source_path == first
    assert index.references[0].source.document_index == 1
    assert ir.to_json() == compile_paths([second, first])[2].to_json()
    assert len(docs) == 5


def test_provider_stage_order_changes_order_without_creating_edges(tmp_path):
    path = write(
        tmp_path,
        [
            provider("a", lifecycle={"stage": "late"}),
            provider("z", lifecycle={"stage": "early"}),
            stage("early", -10),
            stage("late", 0),
        ],
    )
    _, _, _, facts, graph, analysis = compile_paths([path])
    assert facts.dependencies == graph.edges == ()
    assert len(facts.stage_assignments) == 2
    assert analysis.order == ("Provider/z", "Provider/a", "Stage/early", "Stage/late")
    assert analysis.assignments["Provider/z"].order == -10
    assert analysis.assignments["Provider/a"].order == 0


@pytest.mark.parametrize(
    "field,target", [("stage", "Stage/missing"), ("depends_on", "Provider/missing")]
)
def test_missing_envelope_references_still_fail(tmp_path, field, target):
    resource = provider(
        **(
            {"lifecycle": {"stage": "missing"}}
            if field == "stage"
            else {"depends_on": [target]}
        )
    )
    with pytest.raises(ResourceResolutionError) as caught:
        resolve_resources(load_yaml_files([write(tmp_path, [resource])]))
    assert caught.value.diagnostic.code == "missing_reference"
    assert caught.value.diagnostic.reference == target


def test_normalized_config_is_deterministic_detached_and_exports_are_fresh(tmp_path):
    data = provider(spec={"driver": "custom.driver", "config": opaque_config()})
    path = write(tmp_path, [data])
    docs, index, ir, _, _, _ = compile_paths([path])
    portable = ir.to_json()
    reordered = deepcopy(data)
    reordered["spec"]["config"] = dict(
        reversed(list(reordered["spec"]["config"].items()))
    )
    alternate = write(tmp_path, [reordered], "renamed.yml")
    assert compile_paths([alternate])[2].to_json() == portable
    assert portable == ir.to_json()
    assert json.loads(portable) == ir.to_dict()
    assert str(path) not in portable
    docs[0].data["spec"]["config"]["future"].clear()
    index.resources["Provider/primary"].resource.spec.config["credentials"].clear()
    exported = ir.to_dict()
    exported["resources"]["Provider/primary"]["spec"]["config"]["future"].clear()
    exported_resource = ir.resources["Provider/primary"].to_dict()
    exported_resource["spec"]["config"].clear()
    assert ir.to_json() == portable
    assert ir.to_dict()["resources"]["Provider/primary"] == data


@pytest.mark.parametrize("literal", [".nan", ".inf", "-.inf", "2026-01-01"])
def test_yaml_values_outside_json_are_schema_failures(tmp_path, literal):
    text = yaml.safe_dump(provider())
    text = text.replace("config: {}", f"config:\n    nested: [{literal}]")
    path = tmp_path / "input.yml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ResourceResolutionError) as caught:
        resolve_resources(load_yaml_files([path]))
    assert caught.value.diagnostic.code == "invalid_resource"
    assert caught.value.diagnostic.field_path[:2] == ("spec", "config")


def test_yaml_non_string_config_keys_fail_in_loader(tmp_path):
    path = write(
        tmp_path,
        [
            provider(
                spec={"driver": "example.driver", "config": {"nested": [{1: "bad"}]}}
            )
        ],
    )
    with pytest.raises(YamlLoadError) as caught:
        load_yaml_files([path])
    assert caught.value.code == "invalid_mapping_key"


def test_provider_only_cli_outputs_and_no_config_disclosure(tmp_path):
    path = write(
        tmp_path,
        [provider(spec={"driver": "unregistered.future", "config": opaque_config()})],
    )
    valid = runner.invoke(app, ["validate", str(path)])
    assert valid.exit_code == 0 and valid.stderr == ""
    assert valid.stdout == "Validated 1 resource; resolved 0 declared references.\n"
    graph = runner.invoke(app, ["graph", str(path)])
    assert graph.exit_code == 0 and graph.stderr == ""
    assert (
        graph.stdout
        == """Logical dependency graph (offline, not an execution plan)
Resources: 1; dependency edges: 0; declared reasons: 0; Stage assignments: 0

Vertices (1):
  Provider/primary

Dependencies (0):
  (none)

Stage assignments (0):
  (none)

Topological order (1):
  1. Provider/primary
"""
    )
    assert "example/token" not in graph.output
    assert "provider.invalid" not in graph.output
    assert "unregistered.future" not in graph.output


@pytest.mark.parametrize("command", ["validate", "graph"])
def test_cli_reports_provider_schema_failures_without_config_contents(
    tmp_path, command
):
    data = provider()
    data["spec"].pop("driver")
    data["spec"]["config"] = opaque_config()
    path = write(tmp_path, [data])
    result = runner.invoke(app, [command, str(path)])
    assert result.exit_code == 1 and result.stdout == ""
    assert "invalid_resource" in result.stderr and "field=spec.driver" in result.stderr
    assert (
        "example/token" not in result.stderr and "provider.invalid" not in result.stderr
    )
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", ["validate", "graph"])
def test_cli_with_provider_dependencies_and_stage_has_no_filesystem_writes(
    tmp_path, monkeypatch, command
):
    monkeypatch.chdir(tmp_path)
    path = write(
        tmp_path,
        [
            provider(depends_on=["Stage/platform"], lifecycle={"stage": "platform"}),
            stage(),
        ],
    )
    before = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    result = runner.invoke(app, [command, path.name])
    assert result.exit_code == 0 and result.stderr == ""
    if command == "validate":
        assert (
            result.stdout == "Validated 2 resources; resolved 2 declared references.\n"
        )
    else:
        assert (
            "Resources: 2; dependency edges: 1; "
            "declared reasons: 1; Stage assignments: 1" in result.stdout
        )
        assert "Stage/platform -> Provider/primary" in result.stdout
        assert "explicit: owner=Provider/primary field=depends_on[0]" in result.stdout
        assert "Provider/primary -> Stage/platform (order=20)" in result.stdout
    after = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    assert after == before
