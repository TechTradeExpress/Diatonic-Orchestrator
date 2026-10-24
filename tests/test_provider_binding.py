"""Binding declarations validate Provider targets without selecting or adding edges."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from typing import Any

import pytest
import yaml
from pydantic import TypeAdapter, ValidationError
from typer.testing import CliRunner

from diatonic.cli import app
from diatonic.compiler.dependencies import classify_dependencies
from diatonic.compiler.graph import build_dependency_graph
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.normalize import normalize_resources
from diatonic.compiler.provider_bindings import (
    ProviderBindingValidationError,
    validate_provider_bindings,
)
from diatonic.compiler.references import ResourceResolutionError, resolve_resources
from diatonic.compiler.stages import analyze_stage_order
from diatonic.model import (
    ProviderBinding,
    ProviderBindingMatch,
    ProviderBindingSpec,
    ProviderReference,
    Resource,
    ResourceBase,
    parse_resource,
)

runner = CliRunner()


def binding(name="lab-vm-provision", **fields) -> dict[str, Any]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": "ProviderBinding",
        "metadata": {"name": name},
        "spec": {
            "capability": "virtual_machine.provision",
            "match": {"kind": "VirtualMachine", "labels": {"site": "lab"}},
            "provider": "Provider/primary",
            "priority": 100,
        },
        **fields,
    }


def provider(name="primary", **fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Provider",
        "metadata": {"name": name},
        "spec": {"driver": "example.unregistered", "config": {}},
        **fields,
    }


def stage(name="platform"):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": name},
        "spec": {"order": 20},
    }


def write(tmp_path, resources, filename="input.yml"):
    path = tmp_path / filename
    path.write_text(yaml.safe_dump_all(resources, sort_keys=False), encoding="utf-8")
    return path


def index_at(tmp_path, resources):
    return resolve_resources(load_yaml_files([write(tmp_path, resources)]))


def portable(result):
    return result.declarations


def test_valid_binding_dispatch_identity_and_roundtrip():
    data = binding()
    result = parse_resource(data)
    assert type(result) is ProviderBinding and isinstance(result, ResourceBase)
    assert type(result.spec) is ProviderBindingSpec
    assert type(result.spec.match) is ProviderBindingMatch
    assert result.identity == "ProviderBinding/lab-vm-provision"
    assert result == ProviderBinding.model_validate(data)
    assert result == ProviderBinding.model_validate_json(json.dumps(data))
    assert result == TypeAdapter(Resource).validate_python(data)
    assert result.model_dump(mode="json", exclude_unset=True) == data
    assert (
        TypeAdapter(ProviderReference).validate_python("Provider/primary", strict=True)
        == "Provider/primary"
    )
    assert result.lifecycle is None and result.depends_on == []
    assert set(ProviderBindingSpec.model_json_schema()["required"]) == {
        "capability",
        "match",
        "provider",
        "priority",
    }


@pytest.mark.parametrize(
    "path",
    [
        ("api_version",),
        ("kind",),
        ("metadata",),
        ("metadata", "name"),
        ("spec",),
        ("spec", "capability"),
        ("spec", "match"),
        ("spec", "match", "kind"),
        ("spec", "provider"),
        ("spec", "priority"),
    ],
)
def test_required_fields(path):
    data = binding()
    parent = data
    for part in path[:-1]:
        parent = parent[part]
    del parent[path[-1]]
    with pytest.raises(ValidationError) as caught:
        parse_resource(data)
    assert caught.value.errors()[0]["type"] in {"missing", "union_tag_not_found"}


@pytest.mark.parametrize(
    "field,value",
    [
        ("capability", ""),
        ("capability", " "),
        ("capability", "a b"),
        ("capability", "a/b"),
        ("capability", 1),
        ("capability", True),
        ("capability", None),
        ("capability", []),
        ("capability", b"capability"),
        ("match", None),
        ("match", []),
        ("match", "VirtualMachine"),
        ("match", {}),
        ("match", {"kind": ""}),
        ("match", {"kind": "bad kind"}),
        ("match", {"kind": "Kind/name"}),
        ("match", {"kind": 1}),
        ("match", {"kind": True}),
        ("match", {"kind": None}),
        ("match", {"kind": "VirtualMachine", "labels": None}),
        ("match", {"kind": "VirtualMachine", "labels": []}),
        ("match", {"kind": "VirtualMachine", "labels": {"site": 1}}),
        ("match", {"kind": "VirtualMachine", "labels": {"site": True}}),
        ("match", {"kind": "VirtualMachine", "labels": {"site": {"in": ["lab"]}}}),
        ("match", {"kind": "VirtualMachine", "labels": {1: "lab"}}),
        ("provider", "Provider"),
        ("provider", "Provider/"),
        ("provider", "/primary"),
        ("provider", "Provider/a/b"),
        ("provider", "Provider/bad name"),
        ("provider", "Network/primary"),
        ("provider", "Stage/primary"),
        ("provider", "provider/primary"),
        ("provider", None),
        ("provider", 1),
        ("provider", True),
        ("provider", []),
        ("provider", b"Provider/primary"),
        ("priority", True),
        ("priority", False),
        ("priority", 1.0),
        ("priority", "100"),
        ("priority", None),
        ("priority", []),
    ],
)
def test_strict_spec_fields(field, value):
    data = binding()
    data["spec"][field] = value
    with pytest.raises(ValidationError):
        parse_resource(data)


@pytest.mark.parametrize(
    "match",
    [
        {"kind": "*"},
        {"kind": "Virtual*"},
        {"kind": "Virtual?achine"},
        {"kind": "[VirtualMachine]"},
        {"kind": "VirtualMachine|Image"},
        {"kind": "kind!=Image"},
        {"kind": "VirtualMachine", "expressions": []},
        {"kind": "VirtualMachine", "matchExpressions": []},
        {"kind": "VirtualMachine", "operator": "In"},
        {"kind": "VirtualMachine", "labels": {"site": "*"}},
        {"kind": "VirtualMachine", "labels": {"site": "lab?"}},
        {"kind": "VirtualMachine", "labels": {"site!=": "lab"}},
        {"kind": "VirtualMachine", "labels": {"site": ">=lab"}},
    ],
)
def test_unsupported_selector_grammar_is_rejected(match):
    with pytest.raises(ValidationError):
        ProviderBindingMatch.model_validate(match)


@pytest.mark.parametrize(
    "capability,kind",
    [
        ("virtual_machine.provision", "VirtualMachine"),
        ("future.custom:operation", "FutureResource"),
        ("arbitrary", "future-kind"),
        ("custom.capability", "future-kind.v2"),
    ],
)
def test_identifiers_are_not_allowlisted_and_matching_resources_are_not_required(
    tmp_path, capability, kind
):
    data = binding()
    data["spec"].update(capability=capability, match={"kind": kind})
    result = validate_provider_bindings(index_at(tmp_path, [data, provider()]))
    assert result.declarations[0].capability == capability
    assert result.declarations[0].match_kind == kind
    assert dict(result.declarations[0].match_labels) == {}


@pytest.mark.parametrize("priority", [-100, 0, 100, 2**64])
def test_signed_priorities_have_no_default_or_ranking(tmp_path, priority):
    data = binding()
    data["spec"]["priority"] = priority
    other = deepcopy(data)
    other["metadata"]["name"] = "another"
    result = validate_provider_bindings(index_at(tmp_path, [data, other, provider()]))
    assert len(result.declarations) == 2
    assert all(declaration.priority == priority for declaration in result.declarations)


def test_labels_are_fresh_optional_maps_with_exact_values():
    omitted = ProviderBindingMatch(kind="FutureResource")
    another = ProviderBindingMatch(kind="FutureResource")
    explicit = ProviderBindingMatch(kind="FutureResource", labels={})
    omitted.labels["site"] = "lab"
    assert another.labels == explicit.labels == {}
    labels = {"site": "lab", "role": "application", "version": "1.2"}
    first = ProviderBindingMatch(kind="FutureResource", labels=labels)
    second = ProviderBindingMatch(kind="FutureResource", labels=labels)
    first.labels["site"] = "changed"
    assert second.labels == labels
    assert another.model_dump(exclude_unset=True) == {"kind": "FutureResource"}
    assert explicit.model_dump(exclude_unset=True) == {
        "kind": "FutureResource",
        "labels": {},
    }


@pytest.mark.parametrize("level", ["resource", "spec", "match"])
def test_unknown_fields_fail(level):
    data = binding()
    target = (
        data
        if level == "resource"
        else data["spec"]
        if level == "spec"
        else data["spec"]["match"]
    )
    target["unknown"] = True
    with pytest.raises(ValidationError) as caught:
        parse_resource(data)
    assert caught.value.errors()[0]["type"] == "extra_forbidden"


@pytest.mark.parametrize("kind", ["Provider", "providerbinding", "Unknown", "Project"])
def test_wrong_kind_is_rejected_by_concrete_model(kind):
    with pytest.raises(ValidationError):
        ProviderBinding.model_validate(binding(kind=kind))


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_version", "iac/v0alpha2"),
        ("metadata", {"name": 1}),
        ("metadata", {"name": "bad/name"}),
        ("depends_on", ["bad"]),
        ("lifecycle", {"prevent_destroy": "true"}),
        ("extensions", {"platform": {"bad": object()}}),
    ],
)
def test_shared_envelope_validation_is_preserved(field, value):
    with pytest.raises(ValidationError):
        parse_resource(binding(**{field: value}))


def test_shared_envelope_is_preserved_in_ir(tmp_path):
    data = binding(
        metadata={
            "name": "lab-vm-provision",
            "description": "Example",
            "labels": {"site": "lab"},
            "annotations": {"owner": "example"},
        },
        lifecycle={
            "stage": "platform",
            "desired_state": "absent",
            "phases": {"observe": "external"},
            "prevent_destroy": True,
        },
        depends_on=["Provider/primary"],
        extensions={"platform": {"feature": True}},
    )
    index = index_at(tmp_path, [data, provider(), stage()])
    result = validate_provider_bindings(index)
    assert (
        normalize_resources(index).to_dict()["resources"][
            "ProviderBinding/lab-vm-provision"
        ]
        == data
    )
    assert result.declarations[0].provider_identity == "Provider/primary"
    assert (
        index.resources[
            "ProviderBinding/lab-vm-provision"
        ].resource.lifecycle.phases.provision
        is None
    )


@pytest.mark.parametrize(
    "other", [stage("primary"), provider("other"), provider("Primary")]
)
def test_missing_provider_has_no_same_name_driver_or_case_fallback(tmp_path, other):
    path = write(tmp_path, [binding(), other])
    index = resolve_resources(load_yaml_files([path]))
    assert index.references == ()  # This remains outside M1.5 reference resolution.
    with pytest.raises(ProviderBindingValidationError) as caught:
        validate_provider_bindings(index)
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "missing_binding_provider"
    assert diagnostic.resource_identity == "ProviderBinding/lab-vm-provision"
    assert diagnostic.provider_identity == "Provider/primary"
    assert diagnostic.field_path == ("spec", "provider")
    assert (
        diagnostic.source.source_path,
        diagnostic.source.document_index,
        diagnostic.source.line,
        diagnostic.source.column,
    ) == (path, 1, 1, 1)
    assert "root line" in str(caught.value)
    assert "field=spec.provider" in str(caught.value)


def test_multiple_bindings_and_equal_priorities_are_not_ambiguous(tmp_path):
    resources = [binding("z"), binding("A"), binding("a"), provider()]
    resources[1]["spec"]["priority"] = 1000
    resources[2]["spec"]["priority"] = -100
    result = validate_provider_bindings(index_at(tmp_path, resources))
    assert [d.resource_identity for d in result.declarations] == [
        "ProviderBinding/A",
        "ProviderBinding/a",
        "ProviderBinding/z",
    ]
    assert [d.priority for d in result.declarations] == [1000, -100, 100]
    assert all(d.provider_identity == "Provider/primary" for d in result.declarations)


def test_cross_file_forward_links_case_and_file_layout_independence(tmp_path):
    first = write(tmp_path, [binding("z"), binding("a")], "bindings.yml")
    second = write(tmp_path, [provider()], "providers.yml")
    results = []
    for paths in ([first, second], [second, first]):
        index = resolve_resources(load_yaml_files(paths))
        results.append(validate_provider_bindings(index))
        assert index.references == ()
    assert results[0] == results[1]
    renamed = write(tmp_path, [provider(), binding("a"), binding("z")], "renamed.yml")
    relocated = validate_provider_bindings(
        resolve_resources(load_yaml_files([renamed]))
    )
    assert portable(relocated) == portable(results[0])
    assert relocated.sources != results[0].sources


def test_missing_target_error_order_is_independent_of_document_order(tmp_path):
    resources = [binding("z"), binding("A"), binding("a")]
    for order in (resources, list(reversed(resources))):
        with pytest.raises(ProviderBindingValidationError) as caught:
            validate_provider_bindings(index_at(tmp_path, order))
        assert caught.value.diagnostic.resource_identity == "ProviderBinding/A"
        assert caught.value.diagnostic.code == "missing_binding_provider"


@pytest.mark.parametrize("across_files", [False, True])
def test_duplicate_binding_identity_retains_both_roots(tmp_path, across_files):
    first = write(tmp_path, [binding()], "first.yml")
    second = write(tmp_path, [binding()], "second.yml")
    if not across_files:
        first = write(tmp_path, [binding(), binding()], "stream.yml")
    with pytest.raises(ResourceResolutionError) as caught:
        resolve_resources(load_yaml_files([first, second] if across_files else [first]))
    diagnostic = caught.value.diagnostic
    assert diagnostic.code == "duplicate_identity"
    assert diagnostic.resource_identity == "ProviderBinding/lab-vm-provision"
    assert diagnostic.related_source.source_path == first
    assert diagnostic.related_source.document_index == 1
    assert diagnostic.source.source_path == (second if across_files else first)
    assert diagnostic.source.document_index == (1 if across_files else 2)


def test_configuration_link_is_not_a_graph_edge_or_stage_assignment(tmp_path):
    index = index_at(tmp_path, [binding("primary"), provider()])
    declarations = validate_provider_bindings(index)
    facts = classify_dependencies(index)
    graph = build_dependency_graph(index, facts)
    analysis = analyze_stage_order(index, graph)
    assert (
        index.references
        == facts.dependencies
        == facts.stage_assignments
        == graph.edges
        == ()
    )
    assert graph.vertices == ("Provider/primary", "ProviderBinding/primary")
    assert analysis.order == graph.vertices
    assert not analysis.assignments
    assert len(declarations.declarations) == 1
    assert graph.sources["Provider/primary"].document_index == 2


def test_only_explicit_dependencies_create_edges_and_stage_is_separate(tmp_path):
    data = binding(
        depends_on=["Provider/primary", "Provider/primary"],
        lifecycle={"stage": "platform"},
    )
    index = index_at(tmp_path, [data, provider(), stage()])
    validate_provider_bindings(index)
    facts = classify_dependencies(index)
    graph = build_dependency_graph(index, facts)
    analysis = analyze_stage_order(index, graph)
    assert [r.field_path for r in index.references] == [
        ("depends_on", 0),
        ("depends_on", 1),
        ("lifecycle", "stage"),
    ]
    assert len(graph.edges) == 1 and len(graph.edges[0].reasons) == 2
    assert graph.edges[0].prerequisite_identity == "Provider/primary"
    assert graph.edges[0].dependent_identity == "ProviderBinding/lab-vm-provision"
    assert all(reason.classification == "explicit" for reason in graph.edges[0].reasons)
    assert analysis.assignments["ProviderBinding/lab-vm-provision"].order == 20
    assert len(facts.stage_assignments) == 1


def test_immutable_summary_no_mutation_and_detached_provenance(tmp_path):
    path = write(tmp_path, [binding(), provider()])
    docs = load_yaml_files([path])
    before = deepcopy(docs)
    index = resolve_resources(docs)
    ir = normalize_resources(index)
    before_ir = ir.to_json()
    result = validate_provider_bindings(index)
    assert docs == before
    assert normalize_resources(index).to_json() == before_ir
    declaration = result.declarations[0]
    assert not hasattr(result, "__dict__") and not hasattr(declaration, "__dict__")
    for identity, source in result.sources.items():
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
        assert source is not original and not hasattr(source, "__dict__")
    with pytest.raises(FrozenInstanceError):
        declaration.priority = 0
    with pytest.raises(TypeError):
        declaration.match_labels["site"] = "changed"
    with pytest.raises(TypeError):
        result.sources["new"] = None
    with pytest.raises(FrozenInstanceError):
        result.sources[declaration.resource_identity].line = 999
    with pytest.raises(FrozenInstanceError):
        result.declarations = ()
    model = index.resources[declaration.resource_identity].resource
    model.spec.match.labels["site"] = "changed"
    model.spec.provider = "Provider/changed"
    model.spec.priority = -1
    docs[0].data["spec"]["capability"] = "changed"
    index.resources["Provider/primary"].resource.spec.config["data"] = [1, 2]
    assert declaration.provider_identity == "Provider/primary"
    assert declaration.match_labels == {"site": "lab"} and declaration.priority == 100
    assert declaration.capability == "virtual_machine.provision"
    assert ir.to_json() == before_ir
    sources = dict(result.sources)
    labels = dict(declaration.match_labels)
    copied = replace(
        result,
        declarations=(replace(declaration, match_labels=labels),),
        sources=sources,
    )
    labels.clear()
    sources.clear()
    assert copied == result
    assert not hasattr(declaration, "config") and not hasattr(declaration, "resource")


def test_empty_index_and_no_binding_results(tmp_path):
    result = validate_provider_bindings(resolve_resources([]))
    assert result.declarations == () and dict(result.sources) == {}
    assert (
        validate_provider_bindings(index_at(tmp_path, [provider()])).declarations == ()
    )
    with pytest.raises(TypeError, match="ResourceIndex"):
        validate_provider_bindings({})


@pytest.mark.parametrize("command", ["validate", "graph"])
def test_cli_valid_binding_is_offline_and_config_link_not_counted(tmp_path, command):
    path = write(tmp_path, [binding(), provider()])
    result = runner.invoke(app, [command, str(path)])
    assert result.exit_code == 0 and result.stderr == ""
    if command == "validate":
        assert (
            result.stdout == "Validated 2 resources; resolved 0 declared references.\n"
        )
    else:
        assert (
            result.stdout
            == """Logical dependency graph (offline, not an execution plan)
Resources: 2; dependency edges: 0; declared reasons: 0; Stage assignments: 0

Vertices (2):
  Provider/primary
  ProviderBinding/lab-vm-provision

Dependencies (0):
  (none)

Stage assignments (0):
  (none)

Topological order (2):
  1. Provider/primary
  2. ProviderBinding/lab-vm-provision
"""
        )
    assert "example.unregistered" not in result.output
    assert "virtual_machine.provision" not in result.output


@pytest.mark.parametrize("command", ["validate", "graph"])
def test_cli_missing_provider_has_literal_actionable_diagnostic(tmp_path, command):
    data = binding("[red]binding")
    data["spec"]["provider"] = "Provider/[bold]missing"
    path = tmp_path / "[underline]bindings.yml"
    path.write_text("# comment\n---\n" + yaml.safe_dump(data), encoding="utf-8")
    result = runner.invoke(app, [command, str(path)])
    assert result.exit_code == 1 and result.stdout == ""
    assert result.stderr == (
        f"{path} (document 1, root line 3, column 1): missing_binding_provider; "
        "resource=ProviderBinding/[red]binding; field=spec.provider; "
        "target=Provider/[bold]missing; undeclared Provider target\n"
    )
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", ["validate", "graph"])
def test_cli_wrong_kind_reference_fails_at_schema_stage(tmp_path, command):
    data = binding()
    data["spec"]["provider"] = "Stage/primary"
    path = write(tmp_path, [data, stage("primary")])
    result = runner.invoke(app, [command, str(path)])
    assert result.exit_code == 1 and result.stdout == ""
    assert "invalid_resource" in result.stderr
    assert "field=spec.provider" in result.stderr
    assert "reference must target Provider/name" in result.stderr
    assert "missing_binding_provider" not in result.stderr
    assert "Traceback" not in result.output


@pytest.mark.parametrize("command", ["validate", "graph"])
@pytest.mark.parametrize("valid", [True, False])
def test_cli_no_filesystem_writes_or_provider_config_disclosure(
    tmp_path, monkeypatch, command, valid
):
    monkeypatch.chdir(tmp_path)
    instance = provider()
    instance["spec"]["config"] = {
        "credentials": {"token": {"secret_ref": "example/not-resolved"}}
    }
    data = binding()
    if not valid:
        data["spec"]["provider"] = "Provider/missing"
    path = write(tmp_path, [data, instance])
    before = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    result = runner.invoke(app, [command, path.name])
    assert result.exit_code == (0 if valid else 1)
    assert "example/not-resolved" not in result.output
    assert "example.unregistered" not in result.output
    after = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    assert after == before


@pytest.mark.parametrize("command", ["validate", "graph"])
def test_cli_shared_links_keep_existing_counts_and_graph_reasons(tmp_path, command):
    data = binding(depends_on=["Provider/primary"], lifecycle={"stage": "platform"})
    first = write(tmp_path, [data], "binding.yml")
    second = write(tmp_path, [provider(), stage()], "targets.yml")
    result = runner.invoke(app, [command, str(first), str(second)])
    assert result.exit_code == 0 and result.stderr == ""
    if command == "validate":
        assert (
            result.stdout == "Validated 3 resources; resolved 2 declared references.\n"
        )
    else:
        assert (
            "Resources: 3; dependency edges: 1; "
            "declared reasons: 1; Stage assignments: 1" in result.stdout
        )
        assert "Provider/primary -> ProviderBinding/lab-vm-provision" in result.stdout
        assert (
            "explicit: owner=ProviderBinding/lab-vm-provision field=depends_on[0]"
            in result.stdout
        )
        assert (
            "ProviderBinding/lab-vm-provision -> Stage/platform (order=20)"
            in result.stdout
        )
        assert "field=spec.provider" not in result.stdout


@pytest.mark.parametrize("command", ["validate", "graph"])
def test_cli_usage_exit_two_is_unchanged(command):
    result = runner.invoke(app, [command])
    assert result.exit_code == 2
    assert "Usage:" in result.stderr


@pytest.mark.parametrize(
    "mutation,message",
    [
        ("binding-identity", "indexed identity mismatch"),
        ("binding-metadata", "indexed identity mismatch"),
        ("binding-type", "binding type"),
        ("binding-spec", "validated ProviderBindingSpec"),
        ("binding-priority", "no longer satisfies its schema"),
        ("binding-target", "no longer satisfies its schema"),
        ("binding-match", "no longer satisfies its schema"),
        ("binding-source", "document-root provenance"),
        ("target-type", "not a typed Provider"),
        ("target-identity", "not a typed Provider"),
        ("target-source", "document-root provenance"),
        ("target-record", "indexed Provider record"),
    ],
)
def test_mutated_and_incompatible_inputs_are_controlled(tmp_path, mutation, message):
    index = index_at(tmp_path, [binding(), provider(), stage()])
    entries = dict(index.resources)
    owner = "ProviderBinding/lab-vm-provision"
    model = entries[owner].resource
    target = entries["Provider/primary"].resource
    if mutation == "binding-identity":
        model.metadata.name = "changed"
    elif mutation == "binding-metadata":
        model.metadata = None
    elif mutation == "binding-type":
        entries[owner] = replace(
            entries[owner], resource=ResourceBase.model_validate(binding())
        )
    elif mutation == "binding-spec":
        model.spec = {}
    elif mutation == "binding-priority":
        model.spec.priority = True
    elif mutation == "binding-target":
        model.spec.provider = "Stage/platform"
    elif mutation == "binding-match":
        model.spec.match.labels["site"] = {"in": ["lab"]}
    elif mutation == "binding-source":
        entries[owner] = replace(entries[owner], source=None)
    elif mutation == "target-type":
        entries["Provider/primary"] = replace(
            entries["Provider/primary"],
            resource=ResourceBase.model_validate(provider()),
        )
    elif mutation == "target-identity":
        target.metadata.name = "changed"
    elif mutation == "target-source":
        entries["Provider/primary"] = replace(entries["Provider/primary"], source=None)
    else:
        entries["Provider/primary"] = None
    with pytest.raises(ProviderBindingValidationError, match=message) as caught:
        validate_provider_bindings(replace(index, resources=entries))
    assert caught.value.diagnostic.code == "invalid_binding_input"
    assert caught.value.diagnostic.resource_identity == owner
    assert caught.value.diagnostic.field_path == ("spec", "provider")
    if mutation in {"target-type", "target-identity", "target-source", "target-record"}:
        assert caught.value.diagnostic.provider_identity == "Provider/primary"
        assert caught.value.diagnostic.source is not None


def test_invalid_binding_records_keys_and_absent_position_are_controlled(tmp_path):
    index = index_at(tmp_path, [binding(), provider()])
    owner = "ProviderBinding/lab-vm-provision"
    records = dict(index.resources)
    records[owner] = None
    with pytest.raises(ProviderBindingValidationError, match="indexed binding record"):
        validate_provider_bindings(replace(index, resources=records))
    with pytest.raises(
        ProviderBindingValidationError, match="identity keys must be strings"
    ):
        validate_provider_bindings(
            replace(index, resources={1: index.resources[owner]})
        )
    missing_source = replace(index.resources[owner].source, line=None, column=None)
    records[owner] = replace(index.resources[owner], source=missing_source)
    records.pop("Provider/primary")
    with pytest.raises(ProviderBindingValidationError) as caught:
        validate_provider_bindings(replace(index, resources=records))
    assert "document 1" in str(caught.value)
    assert "root line" not in str(caught.value)


def test_normalization_preserves_omitted_and_explicit_empty_labels(tmp_path):
    first = binding("omitted")
    first["spec"]["match"] = {"kind": "FutureKind"}
    second = binding("explicit")
    second["spec"]["match"] = {"kind": "FutureKind", "labels": {}}
    index = index_at(tmp_path, [first, second, provider()])
    result = validate_provider_bindings(index)
    ir = normalize_resources(index)
    exported = ir.to_dict()["resources"]
    assert "labels" not in exported["ProviderBinding/omitted"]["spec"]["match"]
    assert exported["ProviderBinding/explicit"]["spec"]["match"]["labels"] == {}
    assert all(dict(d.match_labels) == {} for d in result.declarations)
    assert json.loads(ir.to_json()) == ir.to_dict()


def test_configuration_link_does_not_close_an_explicit_dependency_cycle(tmp_path):
    path = write(
        tmp_path, [binding(), provider(depends_on=["ProviderBinding/lab-vm-provision"])]
    )
    index = resolve_resources(load_yaml_files([path]))
    validate_provider_bindings(index)
    graph = build_dependency_graph(index, classify_dependencies(index))
    assert len(graph.edges) == 1
    assert graph.edges[0].prerequisite_identity == "ProviderBinding/lab-vm-provision"
    assert graph.edges[0].dependent_identity == "Provider/primary"
    assert analyze_stage_order(index, graph).order == (
        "ProviderBinding/lab-vm-provision",
        "Provider/primary",
    )
    result = runner.invoke(app, ["graph", str(path)])
    assert result.exit_code == 0 and result.stderr == ""


def test_first_missing_target_is_canonical_across_file_permutations(tmp_path):
    first = write(tmp_path, [binding("z")], "a-file.yml")
    second = write(tmp_path, [binding("A")], "z-file.yml")
    diagnostics = []
    for paths in ([first, second], [second, first]):
        with pytest.raises(ProviderBindingValidationError) as caught:
            validate_provider_bindings(resolve_resources(load_yaml_files(paths)))
        diagnostics.append(caught.value.diagnostic)
    assert diagnostics[0] == diagnostics[1]
    assert diagnostics[0].resource_identity == "ProviderBinding/A"
    assert diagnostics[0].source.source_path == second
