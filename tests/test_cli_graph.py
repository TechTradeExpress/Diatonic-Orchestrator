"""Provider-free CLI composition, stable literal text, and validation compatibility."""

from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import diatonic.cli as cli
from diatonic import __version__
from diatonic.compiler.dependencies import (
    DependencyClassificationError,
    classify_dependencies,
)
from diatonic.compiler.graph import DependencyGraphInputError, build_dependency_graph
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.references import resolve_resources
from diatonic.compiler.stages import StageOrderInputError, analyze_stage_order

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/infrastructure/resources.yml"
STAGES = ROOT / "tests/fixtures/reference-stages.yml"
runner = CliRunner()

FULL_OUTPUT = """Logical dependency graph (offline, not an execution plan)
Resources: 6; dependency edges: 3; declared reasons: 3; Stage assignments: 2

Vertices (6):
  Hypervisor/host01
  Image/debian13
  Network/servers
  Stage/platform
  Stage/workloads
  VirtualMachine/app01

Dependencies (3):
  Hypervisor/host01 -> VirtualMachine/app01
    implicit: owner=VirtualMachine/app01 field=spec.placement.target
  Image/debian13 -> VirtualMachine/app01
    implicit: owner=VirtualMachine/app01 field=spec.image.ref
  Network/servers -> VirtualMachine/app01
    implicit: owner=VirtualMachine/app01 field=spec.interfaces[0].network

Stage assignments (2):
  Hypervisor/host01 -> Stage/platform (order=20)
  VirtualMachine/app01 -> Stage/workloads (order=40)

Topological order (6):
  1. Hypervisor/host01
  2. Image/debian13
  3. Network/servers
  4. Stage/platform
  5. Stage/workloads
  6. VirtualMachine/app01
"""


def stage(name="workloads", order=40, **fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": name},
        "spec": {"order": order},
        **fields,
    }


def vm(name="app", assigned=None, depends=()):
    data = {
        "api_version": "iac/v0alpha1",
        "kind": "VirtualMachine",
        "metadata": {"name": name},
        "spec": {"cpu": {"cores": 1}, "memory": {"mib": 512}},
        "depends_on": list(depends),
    }
    if assigned is not None:
        data["lifecycle"] = {"stage": assigned}
    return data


def network(name="servers"):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Network",
        "metadata": {"name": name},
        "spec": {
            "vlan_id": 10,
            "ipv4": {"cidr": "192.0.2.0/24", "gateway": "192.0.2.1"},
        },
    }


def write(tmp_path, documents, name="input.yml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8")
    return path


def invoke(*paths):
    return runner.invoke(cli.app, ["graph", *map(str, paths)])


def failure(result, code):
    assert result.exit_code == 1
    assert result.stdout == ""
    assert code in result.stderr
    assert "Logical dependency graph" not in result.stderr
    assert "Topological order" not in result.stderr
    assert "Traceback" not in result.output
    return result.stderr


def validate_success(*paths):
    result = runner.invoke(cli.app, ["validate", *map(str, paths)])
    assert result.exit_code == 0
    assert result.stderr == ""
    assert result.stdout.startswith("Validated ")
    return result.stdout


@pytest.mark.parametrize("columns", [20, 160])
def test_full_example_exact_portable_output_and_terminal_width(columns):
    result = runner.invoke(
        cli.app, ["graph", str(EXAMPLE), str(STAGES)], env={"COLUMNS": str(columns)}
    )
    assert result.exit_code == 0
    assert result.stdout == FULL_OUTPUT
    assert result.stderr == ""
    assert str(EXAMPLE) not in result.stdout and str(STAGES) not in result.stdout


def test_isolated_resources_have_no_inferred_stage_assignments(tmp_path):
    path = write(tmp_path, [stage("z", -10), stage("A", 100), vm()])
    result = invoke(path)
    assert result.exit_code == 0
    assert result.stderr == ""
    assert (
        result.stdout
        == """Logical dependency graph (offline, not an execution plan)
Resources: 3; dependency edges: 0; declared reasons: 0; Stage assignments: 0

Vertices (3):
  Stage/A
  Stage/z
  VirtualMachine/app

Dependencies (0):
  (none)

Stage assignments (0):
  (none)

Topological order (3):
  1. Stage/A
  2. Stage/z
  3. VirtualMachine/app
"""
    )


def test_empty_library_pipeline_output_without_weakening_cli_or_yaml_rules(capsys):
    # No file can legally contain zero documents. Exercise the command's empty
    # library input directly; missing CLI arguments still exit 2 below.
    cli.graph([])
    captured = capsys.readouterr()
    assert captured.err == ""
    assert (
        captured.out
        == """Logical dependency graph (offline, not an execution plan)
Resources: 0; dependency edges: 0; declared reasons: 0; Stage assignments: 0

Vertices (0):
  (none)

Dependencies (0):
  (none)

Stage assignments (0):
  (none)

Topological order (0):
  (none)
"""
    )


def test_multidocument_forward_cross_file_and_layout_independence(tmp_path):
    machine = vm(assigned="workloads", depends=["Stage/workloads"])
    machine["spec"]["interfaces"] = [{"name": "main", "network": "Network/servers"}]
    resources = [machine, network(), stage()]
    combined = write(tmp_path, resources)
    first = write(tmp_path, [resources[0]], "vm.yml")
    second = write(tmp_path, list(reversed(resources[1:])), "others.yml")
    outputs = [invoke(combined), invoke(first, second), invoke(second, first)]
    assert all(result.exit_code == 0 and result.stderr == "" for result in outputs)
    assert len({result.stdout for result in outputs}) == 1
    output = outputs[0].stdout
    assert (
        "Resources: 3; dependency edges: 2; declared reasons: 2; Stage assignments: 1"
        in output
    )
    assert (
        "  Stage/workloads -> VirtualMachine/app\n"
        "    explicit: owner=VirtualMachine/app field=depends_on[0]" in output
    )
    assert "  VirtualMachine/app -> Stage/workloads (order=40)" in output
    assert "field=lifecycle.stage" not in output  # Assignments are not edge reasons.


def test_all_reasons_and_numeric_interface_indexes_remain_in_order(tmp_path):
    machine = vm(assigned="workloads", depends=["Network/servers"] * 2)
    machine["spec"]["interfaces"] = [
        {"name": f"nic{i}", "network": "Network/servers"} for i in range(12)
    ]
    result = invoke(write(tmp_path, [machine, network(), stage()]))
    assert result.exit_code == 0
    assert result.stderr == ""
    assert (
        "dependency edges: 1; declared reasons: 14; Stage assignments: 1"
        in result.stdout
    )
    expected = "\n".join(
        [
            "  Network/servers -> VirtualMachine/app",
            *[
                f"    explicit: owner=VirtualMachine/app field=depends_on[{i}]"
                for i in range(2)
            ],
            *[
                f"    implicit: owner=VirtualMachine/app "
                f"field=spec.interfaces[{i}].network"
                for i in range(12)
            ],
        ]
    )
    assert expected in result.stdout
    assert result.stdout.count("  Network/servers -> VirtualMachine/app\n") == 1


def test_topological_sequence_uses_stage_analysis_without_resorting(tmp_path):
    path = write(
        tmp_path,
        [
            stage("early", -5),
            stage("same", -5),
            stage("late", 0),
            vm("a", "late"),
            vm("b", "early", ["VirtualMachine/c"]),
            vm("c", "same"),
            vm("z"),
        ],
    )
    result = invoke(path)
    assert result.exit_code == 0
    assert result.stderr == ""
    assert (
        result.stdout.split("Topological order (7):\n")[1]
        == """  1. Stage/early
  2. Stage/late
  3. Stage/same
  4. VirtualMachine/c
  5. VirtualMachine/b
  6. VirtualMachine/a
  7. VirtualMachine/z
"""
    )


@pytest.mark.parametrize("length", [1, 2, 4])
def test_closed_cycles_with_all_repeated_reasons_and_validate_compatibility(
    tmp_path, length
):
    paths = []
    for i in range(length):
        target = f"Stage/n{(i - 1) % length}"
        paths.append(
            write(
                tmp_path,
                [stage(f"n{i}", depends_on=[target, target])],
                f"stage-{i}.yml",
            )
        )
    output = failure(invoke(*reversed(paths)), "dependency_cycle")
    witness = [f"Stage/n{i}" for i in range(length)] + ["Stage/n0"]
    assert output.startswith(f"dependency_cycle: {' -> '.join(witness)}\n")
    assert f"Dependencies ({length}):" in output
    for prerequisite, dependent in zip(witness[:-1], witness[1:], strict=True):
        assert f"  {prerequisite} -> {dependent}\n" in output
        for i in range(2):
            assert f"    explicit: owner={dependent} field=depends_on[{i}]" in output
    assert "Sources (document roots):" in output
    for path in paths:
        assert f"{path} (document 1, root line 1, column 1)" in output
    assert (
        validate_success(*paths)
        == f"Validated {length} resource{'s' if length != 1 else ''}; "
        f"resolved {length * 2} declared references.\n"
    )


def test_exact_literal_self_cycle_diagnostic(tmp_path):
    path = write(
        tmp_path,
        [stage("[red]owner", depends_on=["Stage/[red]owner"])],
        "[bold]input.yml",
    )
    output = failure(invoke(path), "dependency_cycle")
    assert output == (
        "dependency_cycle: Stage/[red]owner -> Stage/[red]owner\n\n"
        "Dependencies (1):\n"
        "  Stage/[red]owner -> Stage/[red]owner\n"
        "    explicit: owner=Stage/[red]owner field=depends_on[0]\n\n"
        "Sources (document roots):\n"
        f"  resource=Stage/[red]owner; {path} (document 1, root line 1, column 1)\n"
    )


def test_cycle_with_implicit_edges_preserves_all_origins(tmp_path):
    net = network()
    net["depends_on"] = ["VirtualMachine/app"]
    machine = vm(depends=["Network/servers"])
    machine["spec"]["interfaces"] = [{"name": "nic", "network": "Network/servers"}]
    output = failure(invoke(write(tmp_path, [net, machine])), "dependency_cycle")
    assert output.startswith(
        "dependency_cycle: Network/servers -> VirtualMachine/app -> Network/servers\n"
    )
    assert "explicit: owner=VirtualMachine/app field=depends_on[0]" in output
    assert (
        "implicit: owner=VirtualMachine/app field=spec.interfaces[0].network" in output
    )
    assert "explicit: owner=Network/servers field=depends_on[0]" in output


@pytest.mark.parametrize("indirect", [False, True])
def test_stage_conflicts_include_witness_assignments_sources_and_validate_success(
    tmp_path, indirect
):
    resources = [
        stage("early", 10),
        stage("late", 40),
        vm("app", "late"),
        vm(
            "base",
            "early",
            ["VirtualMachine/helper" if indirect else "VirtualMachine/app"],
        ),
    ]
    if indirect:
        resources.append(vm("helper", depends=["VirtualMachine/app"]))
    path = write(tmp_path, resources)
    output = failure(invoke(path), "stage_order_conflict")
    witness = [
        "VirtualMachine/app",
        *(["VirtualMachine/helper"] if indirect else []),
        "VirtualMachine/base",
    ]
    assert output.startswith(
        f"stage_order_conflict: dependency path {' -> '.join(witness)}\n"
    )
    assert (
        "Conflicting Stage assignments (2):\n"
        "  VirtualMachine/app -> Stage/late (order=40) field=lifecycle.stage\n"
        "  VirtualMachine/base -> Stage/early (order=10) field=lifecycle.stage\n"
        in output
    )
    for a, b in zip(witness[:-1], witness[1:], strict=True):
        assert f"  {a} -> {b}\n    explicit: owner={b} field=depends_on[0]" in output
    for identity in [*witness, "Stage/early", "Stage/late"]:
        assert f"  resource={identity}; {path} (document " in output
    assert "root line" in output
    validate_success(path)


def test_implicit_stage_conflict_includes_network_and_vm_origins(tmp_path):
    net = network()
    net["lifecycle"] = {"stage": "late"}
    machine = vm(assigned="early")
    machine["spec"]["interfaces"] = [{"name": "nic", "network": "Network/servers"}]
    path = write(tmp_path, [stage("early", 10), stage("late", 40), net, machine])
    output = failure(invoke(path), "stage_order_conflict")
    assert "dependency path Network/servers -> VirtualMachine/app" in output
    assert "Network/servers -> Stage/late (order=40) field=lifecycle.stage" in output
    assert (
        "VirtualMachine/app -> Stage/early (order=10) field=lifecycle.stage" in output
    )
    assert (
        "implicit: owner=VirtualMachine/app field=spec.interfaces[0].network" in output
    )
    validate_success(path)


@pytest.mark.parametrize(
    "text,code",
    [
        ("bad: [", "invalid_yaml"),
        ("x: 1\nx: 2\n", "duplicate_key"),
        ("spec:\n  cpu:\n    cores: 1\n    cores: 2\n", "duplicate_key"),
        ("x: !!python/object/apply:os.system ['false']", "invalid_yaml"),
        ("x: !unsupported value", "invalid_yaml"),
        ("", "empty_document"),
        ("null", "empty_document"),
        ("[]", "invalid_root"),
    ],
)
def test_yaml_errors_remain_source_aware(tmp_path, text, code):
    path = tmp_path / "input.yml"
    path.write_text(text, encoding="utf-8")
    output = failure(invoke(path), code)
    assert str(path) in output
    assert "document 1" in output


@pytest.mark.parametrize("case", ["missing", "directory", "decode"])
def test_file_errors_do_not_scan_directories(tmp_path, case):
    path = tmp_path / "input.yml"
    if case == "directory":
        path = tmp_path
    elif case == "decode":
        path.write_bytes(b"bad: \xff\n")
    output = failure(invoke(path), "decode_error" if case == "decode" else "read_error")
    assert str(path) in output


@pytest.mark.parametrize("across_files", [False, True])
def test_duplicate_identities_report_both_roots(tmp_path, across_files):
    if across_files:
        first = write(tmp_path, [stage()], "first.yml")
        second = write(tmp_path, [stage()], "second.yml")
        paths = [first, second]
    else:
        first = second = write(tmp_path, [stage(), stage()])
        paths = [first]
    output = failure(invoke(*paths), "duplicate_identity")
    assert f"{first} (document 1, root line 1, column 1)" in output
    assert f"{second} (document {1 if across_files else 2}, root line" in output
    assert "first declaration:" in output


@pytest.mark.parametrize(
    "fields,field,target",
    [
        ({"depends_on": ["Network/missing"]}, "depends_on[0]", "Network/missing"),
        ({"lifecycle": {"stage": "missing"}}, "lifecycle.stage", "Stage/missing"),
        (
            {"placement": {"target": "Hypervisor/missing"}},
            "spec.placement.target",
            "Hypervisor/missing",
        ),
        ({"image": {"ref": "Image/missing"}}, "spec.image.ref", "Image/missing"),
        (
            {"interfaces": [{"name": "nic", "network": "Network/missing"}]},
            "spec.interfaces[0].network",
            "Network/missing",
        ),
    ],
)
def test_missing_references_are_not_supplied_implicitly(
    tmp_path, fields, field, target
):
    machine = vm()
    if field.startswith("spec."):
        machine["spec"].update(fields)
    else:
        machine.update(fields)
    output = failure(invoke(write(tmp_path, [machine])), "missing_reference")
    assert f"target={target}" in output
    assert f"field={field}" in output
    assert "root line 1, column 1" in output


def test_infrastructure_without_stage_fixture_fails():
    output = failure(invoke(EXAMPLE), "missing_reference")
    assert "Stage/platform" in output
    assert "document 2" in output


@pytest.mark.parametrize(
    "case,field",
    [
        ("kind", "kind"),
        ("version", "api_version"),
        ("nested", "spec.cpu.cores"),
        ("wrong-reference-kind", "spec.image.ref"),
    ],
)
def test_resource_schema_errors(tmp_path, case, field):
    machine = vm()
    if case == "kind":
        machine["kind"] = "Unknown"
    elif case == "version":
        machine["api_version"] = "iac/v0alpha2"
    elif case == "nested":
        machine["spec"]["cpu"]["cores"] = "4"
    else:
        machine["spec"]["image"] = {"ref": "Network/wrong"}
    output = failure(invoke(write(tmp_path, [machine])), "invalid_resource")
    assert f"field={field}" in output


@pytest.mark.parametrize(
    "case,code",
    [
        ("gateway", "gateway_outside_subnet"),
        ("host", "address_outside_subnet"),
        ("collision", "gateway_address_conflict"),
        ("duplicate", "duplicate_static_ipv4"),
    ],
)
def test_ipv4_semantics_run_before_graph_analysis(tmp_path, case, code):
    net, machine = network(), vm()
    machine["spec"]["interfaces"] = [
        {
            "name": "nic",
            "network": "Network/servers",
            "ipv4": {"mode": "static", "address": "192.0.2.20/24"},
        }
    ]
    resources = [net, machine]
    if case == "gateway":
        net["spec"]["ipv4"]["gateway"] = "198.51.100.1"
    elif case in {"host", "collision"}:
        machine["spec"]["interfaces"][0]["ipv4"]["address"] = (
            "198.51.100.1/24" if case == "host" else "192.0.2.1/24"
        )
    else:
        other = vm("other")
        other["spec"]["interfaces"] = machine["spec"]["interfaces"]
        resources.append(other)
    # A cycle is also present; semantic diagnostics must win by pipeline order.
    machine["depends_on"] = ["VirtualMachine/app"]
    path = write(tmp_path, resources)
    output = failure(invoke(path), code)
    assert "dependency_cycle" not in output
    assert "network=Network/servers" in output
    assert "field=spec." in output
    assert "root line" in output


def test_successful_bracket_names_and_diagnostic_paths_are_literal(tmp_path):
    first = write(tmp_path, [stage("[red]owner")], "[bold]input.yml")
    result = invoke(first)
    assert result.exit_code == 0 and result.stderr == ""
    assert result.stdout.count("Stage/[red]owner") == 2
    missing = write(
        tmp_path,
        [stage("[red]owner", depends_on=["Stage/[bold]missing"])],
        "[underline]bad.yml",
    )
    output = failure(invoke(missing), "missing_reference")
    assert str(missing) in output
    assert "Stage/[red]owner" in output and "Stage/[bold]missing" in output


@pytest.mark.parametrize(
    "args", [["graph"], ["graph", "--unknown"], ["graph", "input.yml", "--unknown"]]
)
def test_usage_exit_two(args):
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 2
    assert "Usage:" in result.stderr
    assert "Logical dependency graph" not in result.stdout


@pytest.mark.parametrize(
    "args", [["--help"], ["--version"], ["validate", "--help"], ["graph", "--help"]]
)
def test_help_and_version_compatibility(args):
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0 and result.stderr == ""
    if args == ["--version"]:
        assert result.stdout == f"Diatonic Orchestrator {__version__}\n"
    elif args == ["--help"]:
        assert "graph" in result.stdout and "validate" in result.stdout
    else:
        assert "FILE" in result.stdout


@pytest.mark.parametrize("case", ["success", "cycle", "stage", "yaml"])
def test_no_source_or_filesystem_mutation(tmp_path, monkeypatch, case):
    monkeypatch.chdir(tmp_path)
    if case == "yaml":
        path = tmp_path / "input.yml"
        path.write_text("x: [", encoding="utf-8")
    else:
        resources = [stage()]
        if case == "cycle":
            resources[0]["depends_on"] = ["Stage/workloads"]
        elif case == "stage":
            resources += [
                stage("early", 0),
                vm("app", "workloads"),
                vm("base", "early", ["VirtualMachine/app"]),
            ]
        path = write(tmp_path, resources)
    before = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    result = invoke(path.name)
    assert result.exit_code == (0 if case == "success" else 1)
    after = {
        p.relative_to(tmp_path): p.read_bytes() if p.is_file() else None
        for p in tmp_path.rglob("*")
    }
    assert after == before


def test_controlled_analysis_error_formatting_uses_real_library_errors(tmp_path):
    # These compatibility errors cannot arise from consistent YAML compilation.
    # Trigger real library guards on altered records, without mocking the pipeline.
    index = resolve_resources(
        load_yaml_files(
            [write(tmp_path, [stage("a"), stage("b", depends_on=["Stage/a"])])]
        )
    )
    ref = replace(index.references[0], field_path=("future", "field"))
    with pytest.raises(DependencyClassificationError) as classification:
        classify_dependencies(replace(index, references=(ref,)))
    text = cli._graph_error_text(classification.value)
    assert "unsupported_reference_field" in text and "field=('future', 'field')" in text
    assert "target=Stage/a" in text and "root line" in text
    facts = classify_dependencies(index)
    with pytest.raises(DependencyGraphInputError) as graph_input:
        build_dependency_graph(index, replace(facts, dependencies=()))
    assert cli._graph_error_text(graph_input.value) == str(graph_input.value)
    graph = build_dependency_graph(index, facts)
    with pytest.raises(StageOrderInputError) as stage_input:
        analyze_stage_order(index, replace(graph, vertices=()))
    assert cli._graph_error_text(stage_input.value) == str(stage_input.value)


@pytest.mark.parametrize(
    "path", [(), ("depends_on", [0]), ("lifecycle", None), "future.field"]
)
def test_unrecognized_classification_paths_are_preserved_without_formatting_errors(
    tmp_path, path
):
    source = write(tmp_path, [stage("a", depends_on=["Stage/a"])])
    index = resolve_resources(load_yaml_files([source]))
    ref = replace(index.references[0], field_path=path)
    with pytest.raises(DependencyClassificationError) as caught:
        classify_dependencies(replace(index, references=(ref,)))
    output = cli._graph_error_text(caught.value)
    assert f"field={path!r}" in output
    assert str(source) in output


def test_closing_markup_in_source_paths_is_literal(tmp_path):
    directory = tmp_path / "["
    directory.mkdir()
    path = write(directory, [stage(depends_on=["Stage/workloads"])], "red]")
    assert "[/red]" in str(path)
    output = failure(invoke(path), "dependency_cycle")
    assert str(path) in output
    assert "[/red]" in output


def test_expected_cycle_diagnostics_precede_stage_conflicts(tmp_path):
    path = write(
        tmp_path,
        [
            stage("early", 10),
            stage("late", 40),
            vm("a", "late", ["VirtualMachine/b"]),
            vm("b", "early", ["VirtualMachine/a"]),
        ],
    )
    output = failure(invoke(path), "dependency_cycle")
    assert "stage_order_conflict" not in output
    validate_success(path)
