"""End-to-end explain contracts through the actual M1/M2 offline pipeline."""

import json
from pathlib import Path

import pytest
import yaml
from rich.text import Text
from typer.main import get_command
from typer.testing import CliRunner

from diatonic import __version__
from diatonic.cli import app
from diatonic.compiler.dependencies import classify_dependencies
from diatonic.compiler.graph import build_dependency_graph
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.references import resolve_resources
from diatonic.compiler.stages import analyze_stage_order

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/infrastructure/resources.yml"
STAGES = ROOT / "tests/fixtures/reference-stages.yml"
runner = CliRunner()
CAPABILITY = "virtual_machine.provision"


def stage(name="workloads", order=40, **fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": name},
        "spec": {"order": order},
        **fields,
    }


def vm(name="app", **fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "VirtualMachine",
        "metadata": {"name": name},
        "spec": {"cpu": {"cores": 1}, "memory": {"mib": 512}},
        **fields,
    }


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


def provider(name="primary", driver="example.driver"):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Provider",
        "metadata": {"name": name},
        "spec": {"driver": driver, "config": {"secret_ref": "opaque/do-not-display"}},
    }


def binding(
    name="primary",
    target="primary",
    priority=100,
    capability=CAPABILITY,
    kind="VirtualMachine",
    labels=None,
):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "ProviderBinding",
        "metadata": {"name": name},
        "spec": {
            "capability": capability,
            "match": {"kind": kind, "labels": labels or {}},
            "provider": f"Provider/{target}",
            "priority": priority,
        },
    }


def managed(**fields):
    return vm(lifecycle={"phases": {"provision": "managed"}}, **fields)


def write(tmp_path, documents, name="input.yml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8")
    return path


def support_file(tmp_path, drivers=None):
    path = tmp_path / "support.json"
    path.write_text(
        json.dumps(
            {
                "drivers": [
                    {"driver_id": "example.driver", "capabilities": [CAPABILITY]}
                ]
                if drivers is None
                else drivers
            }
        ),
        encoding="utf-8",
    )
    return path


def invoke(identity, *paths, phase=None, support=None, columns=80):
    args = ["explain", identity, *map(str, paths)]
    if phase is not None:
        args += ["--phase", phase]
    if support is not None:
        args += ["--support-metadata", str(support)]
    return runner.invoke(app, args, env={"COLUMNS": str(columns)})


def success(result):
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    return result.stdout


def failure(result, code, exit_code=1):
    assert result.exit_code == exit_code, (
        result.exit_code,
        result.output,
        result.exception,
    )
    assert result.stdout == ""
    assert code in result.stderr
    assert "Traceback" not in result.output
    assert "Resource explanation" not in result.stderr
    assert "opaque/do-not-display" not in result.output
    return result.stderr


BASELINE = """Resource explanation (offline, not an execution plan)
Resource: VirtualMachine/app

Direct prerequisites (0):
  (none)

Direct dependents (0):
  (none)

Stage and logical order:
  Stage: unassigned
  Logical topological position: 1 of 1

Declared lifecycle:
  lifecycle: (omitted)
  lifecycle.stage: (omitted)
  lifecycle.desired_state: (omitted)
  lifecycle.prevent_destroy: (omitted)
  lifecycle.phases: (omitted)
  lifecycle.phases.observe: (omitted)
  lifecycle.phases.provision: (omitted)
  lifecycle.phases.configure: (omitted)

Provider resolution: not requested
"""


@pytest.mark.parametrize("columns", [20, 80, 160])
def test_baseline_exact_portable_output_isolated_and_width_independent(
    tmp_path, columns
):
    path = write(tmp_path, [vm()])
    assert success(invoke("VirtualMachine/app", path, columns=columns)) == BASELINE
    assert str(path) not in BASELINE


def test_full_infrastructure_example_and_exact_logical_position():
    output = success(invoke("VirtualMachine/app01", EXAMPLE, STAGES))
    assert "Direct prerequisites (3):" in output
    for field in (
        "spec.placement.target",
        "spec.interfaces[0].network",
        "spec.image.ref",
    ):
        assert f"implicit: owner=VirtualMachine/app01 field={field}" in output
    assert "Stage: Stage/workloads (order=40)" in output
    assert "Logical topological position: 6 of 6" in output
    assert "lifecycle.phases.provision: managed" in output
    assert output.endswith("Provider resolution: not requested\n")
    assert "secret_ref" not in output and "extensions" not in output
    assert str(EXAMPLE) not in output and str(STAGES) not in output


def test_direct_prerequisites_dependents_all_reasons_and_numeric_indexes(tmp_path):
    machine = vm(depends_on=["Network/servers", "Network/servers"])
    machine["spec"]["interfaces"] = [
        {"name": f"eth{i}", "network": "Network/servers"} for i in range(12)
    ]
    path = write(
        tmp_path, [vm("after", depends_on=["VirtualMachine/app"]), machine, network()]
    )
    output = success(invoke("VirtualMachine/app", path))
    assert (
        "Direct prerequisites (1):\n  Network/servers -> VirtualMachine/app" in output
    )
    assert (
        "Direct dependents (1):\n  VirtualMachine/app -> VirtualMachine/after" in output
    )
    assert (
        "Network/servers -> VirtualMachine/after" not in output
    )  # No transitive inference.
    assert (
        output.count("field=depends_on[0]") == 2
    )  # One reason on each direction's edge.
    assert "field=depends_on[1]" in output
    positions = [output.index(f"field=spec.interfaces[{i}].network") for i in range(12)]
    assert positions == sorted(positions)
    assert output.count("implicit: owner=VirtualMachine/app") == 12


def test_explicit_stage_dependency_remains_distinct_from_assignment(tmp_path):
    path = write(
        tmp_path,
        [vm(depends_on=["Stage/workloads"], lifecycle={"stage": "workloads"}), stage()],
    )
    output = success(invoke("VirtualMachine/app", path))
    assert "Stage/workloads -> VirtualMachine/app\n    explicit:" in output
    assert "field=depends_on[0]" in output
    assert "Stage: Stage/workloads (order=40)" in output
    assert "field=lifecycle.stage" not in output
    stage_output = success(invoke("Stage/workloads", path))
    assert "Stage: unassigned" in stage_output
    assert "Direct dependents (1)" in stage_output


@pytest.mark.parametrize(
    "identity", ["Stage/workloads", "Provider/primary", "ProviderBinding/primary"]
)
def test_meta_resources_remain_provider_free_isolated_vertices(tmp_path, identity):
    path = write(tmp_path, [stage(), provider(), binding()])
    output = success(invoke(identity, path))
    assert f"Resource: {identity}\n" in output
    assert "Direct prerequisites (0)" in output and "Direct dependents (0)" in output
    assert "Stage: unassigned" in output
    assert "opaque/do-not-display" not in output
    assert "example.driver" not in output  # No spec dump, even for a Provider.


def test_equal_stage_orders_and_positions_come_from_existing_analysis(tmp_path):
    path = write(
        tmp_path,
        [
            stage("a", -10),
            stage("b", -10),
            vm("z", lifecycle={"stage": "a"}),
            vm("a", lifecycle={"stage": "b"}, depends_on=["VirtualMachine/z"]),
            vm("unassigned"),
        ],
    )
    index = resolve_resources(load_yaml_files([path]))
    graph = build_dependency_graph(index, classify_dependencies(index))
    order = analyze_stage_order(index, graph).order
    for number, identity in enumerate(order, 1):
        output = success(invoke(identity, path))
        assert f"Logical topological position: {number} of {len(order)}" in output


def test_all_lifecycle_values_and_no_operation_inferred(tmp_path):
    document = vm(
        lifecycle={
            "stage": "workloads",
            "desired_state": "absent",
            "prevent_destroy": False,
            "phases": {
                "observe": "external",
                "provision": "managed",
                "configure": "disabled",
            },
        }
    )
    path = write(tmp_path, [document, stage()])
    output = success(invoke("VirtualMachine/app", path))
    for field, value in [
        ("stage", "workloads"),
        ("desired_state", "absent"),
        ("prevent_destroy", "false"),
        ("phases.observe", "external"),
        ("phases.provision", "managed"),
        ("phases.configure", "disabled"),
    ]:
        assert f"lifecycle.{field}: {value}" in output
    assert "Provider resolution: not requested" in output
    assert "Required capability:" not in output


@pytest.mark.parametrize(
    "lifecycle,lines,origin",
    [
        (
            "omitted",
            ["lifecycle: (omitted)", "lifecycle.phases: (omitted)"],
            "lifecycle_omitted",
        ),
        (None, ["lifecycle: null", "lifecycle.phases: (omitted)"], "lifecycle_null"),
        ({}, ["lifecycle: declared", "lifecycle.phases: (omitted)"], "phases_omitted"),
        ({"phases": None}, ["lifecycle.phases: null"], "phases_null"),
        (
            {"phases": {}},
            ["lifecycle.phases: declared", "lifecycle.phases.provision: (omitted)"],
            "phase_omitted",
        ),
        (
            {
                "stage": None,
                "desired_state": None,
                "prevent_destroy": None,
                "phases": {"provision": None},
            },
            [
                "lifecycle.stage: null",
                "lifecycle.desired_state: null",
                "lifecycle.prevent_destroy: null",
                "lifecycle.phases.provision: null",
            ],
            "phase_null",
        ),
    ],
)
def test_lifecycle_omissions_nulls_and_unspecified_phase_origins(
    tmp_path, lifecycle, lines, origin
):
    document = vm()
    if lifecycle != "omitted":
        document["lifecycle"] = lifecycle
    path = write(tmp_path, [document])
    baseline = success(invoke("VirtualMachine/app", path))
    for line in lines:
        assert line in baseline
    output = success(
        invoke(
            "VirtualMachine/app",
            path,
            phase="provision",
            support=tmp_path / "nonexistent.json",
        )
    )
    assert "Ownership: unspecified" in output
    assert f"Declaration origin: {origin}" in output
    assert "Required capability: (none)" in output
    assert "no managed demand or selection" in output


@pytest.mark.parametrize(
    "ownership,description",
    [("external", "externally owned"), ("disabled", "not applicable")],
)
def test_nonmanaged_does_not_read_supplied_metadata_or_select(
    tmp_path, ownership, description
):
    path = write(
        tmp_path,
        [vm(lifecycle={"phases": {"provision": ownership}}), provider(), binding()],
    )
    invalid = tmp_path / "invalid.json"
    invalid.write_text("not JSON and must never be read")
    for support in (None, tmp_path / "missing.json", invalid, tmp_path):
        output = success(
            invoke("VirtualMachine/app", path, phase="provision", support=support)
        )
        assert f"Ownership: {ownership}" in output
        assert (
            f"Provider resolution: {description}; no managed demand or selection"
            in output
        )
        assert "Candidates (" not in output and "ProviderBinding:" not in output


def test_managed_success_exact_selection_and_complete_candidate_trace(tmp_path):
    document = managed(
        metadata={"name": "app", "labels": {"site": "lab", "role": "app"}}
    )
    path = write(
        tmp_path,
        [
            document,
            provider(),
            provider("unknown", "unknown.driver"),
            binding("winner", labels={"site": "lab", "role": "app"}),
            binding("lower", priority=-1),
            binding("unknown", target="unknown", priority=50),
            binding("wrong-cap", capability="other"),
            binding("wrong-kind", kind="Network"),
            binding("wrong-label", labels={"site": "other"}),
            binding("missing-label", labels={"absent": "value"}),
        ],
    )
    support = support_file(tmp_path)
    output = success(
        invoke("VirtualMachine/app", path, phase="provision", support=support)
    )
    assert "Requested phase: provision\n  Ownership: managed" in output
    assert f"Required capability: {CAPABILITY}" in output
    assert "Provider resolution: selected (offline declared support only)" in output
    assert (
        "ProviderBinding: ProviderBinding/winner\n  Provider: Provider/primary\n"
        "  Driver: example.driver\n  Priority: 100" in output
    )
    assert "Candidates (7):" in output
    for name, outcome, reason in [
        ("winner", "selected", "selected_highest_priority"),
        ("lower", "outranked", "lower_priority"),
        ("unknown", "metadata_unavailable", "driver_metadata_unavailable"),
        ("wrong-cap", "rejected", "capability_mismatch"),
        ("wrong-kind", "rejected", "kind_mismatch"),
        ("wrong-label", "rejected", "label_mismatch"),
        ("missing-label", "rejected", "missing_label"),
    ]:
        assert f"ProviderBinding/{name}: {outcome}" in output
        assert reason in output
    assert "field=spec.match.labels.site; expected='other'; actual='lab'" in output
    assert str(path) not in output and str(support) not in output
    assert "opaque/do-not-display" not in output
    assert output.index("ProviderBinding/lower:") < output.index(
        "ProviderBinding/winner:"
    )


@pytest.mark.parametrize(
    "phase,capability",
    [
        ("observe", "virtual_machine.observe"),
        ("configure", "virtual_machine.configure"),
    ],
)
def test_each_cli_phase_queries_only_that_phase(tmp_path, phase, capability):
    path = write(
        tmp_path,
        [
            vm(lifecycle={"phases": {phase: "managed", "provision": "managed"}}),
            provider(),
            binding(capability=capability),
        ],
    )
    support = support_file(
        tmp_path, [{"driver_id": "example.driver", "capabilities": [capability]}]
    )
    output = success(invoke("VirtualMachine/app", path, phase=phase, support=support))
    assert f"Requested phase: {phase}" in output
    assert f"Required capability: {capability}" in output
    assert "Provider resolution: selected" in output


@pytest.mark.parametrize(
    "scenario,code",
    [
        ("no-binding", "no_matching_provider_binding"),
        ("no-match", "no_matching_provider_binding"),
        ("unsupported", "no_supported_provider_binding"),
        ("unknown", "missing_driver_support_metadata"),
        ("empty-metadata", "missing_driver_support_metadata"),
        ("tie-same", "ambiguous_provider_binding"),
        ("tie-different", "ambiguous_provider_binding"),
        ("unknown-high", "missing_driver_support_metadata"),
        ("unknown-equal", "missing_driver_support_metadata"),
    ],
)
def test_resolution_failures_show_codes_candidates_priorities_and_roots(
    tmp_path, scenario, code
):
    documents = [managed(), provider()]
    if scenario != "no-binding":
        documents.append(
            binding("a", kind="Network" if scenario == "no-match" else "VirtualMachine")
        )
    if scenario.startswith("tie"):
        documents += [
            provider("second"),
            binding("b", target="primary" if scenario == "tie-same" else "second"),
        ]
    if scenario.startswith("unknown-"):
        documents += [
            provider("unknown", "unknown.driver"),
            binding(
                "b",
                target="unknown",
                priority=101 if scenario == "unknown-high" else 100,
            ),
        ]
    path = write(tmp_path, documents)
    support = (
        None
        if scenario == "unknown"
        else support_file(
            tmp_path,
            []
            if scenario == "empty-metadata"
            else [
                {
                    "driver_id": "example.driver",
                    "capabilities": [] if scenario == "unsupported" else [CAPABILITY],
                }
            ],
        )
    )
    error = failure(
        invoke("VirtualMachine/app", path, phase="provision", support=support), code
    )
    assert "resource=VirtualMachine/app; phase=provision" in error
    assert f"capability={CAPABILITY}" in error
    assert "Sources (document roots):" in error and str(path) in error
    assert "document 1, root line 1, column 1" in error
    if scenario != "no-binding":
        assert "ProviderBinding/a:" in error and "priority=100" in error
        assert "provider=Provider/primary" in error
    if scenario.startswith("tie"):
        assert "highest_priority_tie: field=spec.priority" in error
        assert "ProviderBinding/b: ambiguous_highest_priority" in error
    if scenario.startswith("unknown") or scenario == "empty-metadata":
        assert "driver_metadata_unavailable: field=spec.provider" in error
    if scenario == "no-match":
        assert "kind_mismatch: field=spec.match.kind" in error
    if scenario == "unsupported":
        assert "driver_capability_unsupported: field=spec.provider" in error


def test_unsupported_managed_phase_preserves_m27_diagnostic_before_metadata_read(
    tmp_path,
):
    path = write(tmp_path, [stage(lifecycle={"phases": {"provision": "managed"}})])
    error = failure(
        invoke(
            "Stage/workloads",
            path,
            phase="provision",
            support=tmp_path / "missing.json",
        ),
        "unsupported_managed_phase",
    )
    assert "resource=Stage/workloads" in error and "root line 1" in error


@pytest.mark.parametrize(
    "identity", ["VirtualMachine/missing", "virtualmachine/app", "VirtualMachine/App"]
)
def test_unknown_case_sensitive_identity(tmp_path, identity):
    path = write(tmp_path, [vm()])
    failure(invoke(identity, path), "unknown_explain_resource")


@pytest.mark.parametrize(
    "identity",
    ["app", "/app", "VirtualMachine/", "VirtualMachine/a/b", "Virtual Machine/app"],
)
def test_invalid_resource_syntax_is_usage_error(tmp_path, identity):
    failure(invoke(identity, tmp_path / "not-read.yml"), "canonical Kind/name", 2)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["VirtualMachine/app"],
        ["VirtualMachine/app", "unused.yml", "--phase", "destroy"],
        ["VirtualMachine/app", "unused.yml", "--support-metadata", "unused.json"],
        ["VirtualMachine/app", "unused.yml", "--unknown"],
    ],
)
def test_missing_arguments_and_invalid_options_are_usage_errors(args):
    result = runner.invoke(app, ["explain", *args])
    assert result.exit_code == 2 and result.stdout == ""
    assert "Usage:" in result.stderr


@pytest.mark.parametrize(
    "text,code",
    [
        ("{", "invalid_support_metadata"),
        ("null", "invalid_support_metadata"),
        ("[]", "invalid_support_metadata"),
        ("{}", "invalid_support_metadata"),
        ('{"drivers": null}', "invalid_support_metadata"),
        ('{"drivers": {}}', "invalid_support_metadata"),
        ('{"drivers": [], "extra": "never-echo-this"}', "invalid_support_metadata"),
        ('{"drivers": [], "drivers": []}', "invalid_support_metadata"),
        ('{"drivers": [null]}', "invalid_support_metadata"),
        ('{"drivers": [{}]}', "invalid_support_metadata"),
        ('{"drivers": [{"driver_id": "example.driver"}]}', "invalid_support_metadata"),
        ('{"drivers": [{"capabilities": []}]}', "invalid_support_metadata"),
        (
            '{"drivers": [{"driver_id": "example.driver", '
            '"capabilities": [], "extra": 0}]}',
            "invalid_support_metadata",
        ),
        (
            '{"drivers": [{"driver_id": "a", "driver_id": "b", "capabilities": []}]}',
            "invalid_support_metadata",
        ),
        (
            '{"drivers": [{"driver_id": "example.driver", "capabilities": {}}]}',
            "invalid_support_metadata",
        ),
        (
            '{"drivers": [{"driver_id": "example.driver", '
            '"capabilities": "virtual_machine.provision"}]}',
            "invalid_support_metadata",
        ),
        (
            '{"drivers": [{"driver_id": "example.driver", "capabilities": [null]}]}',
            "invalid_driver_descriptor",
        ),
        (
            '{"drivers": [{"driver_id": "example.driver", "capabilities": [false]}]}',
            "invalid_driver_descriptor",
        ),
        (
            '{"drivers": [{"driver_id": "example.driver", "capabilities": [""]}]}',
            "invalid_driver_descriptor",
        ),
        (
            '{"drivers": [{"driver_id": "example.driver", "capabilities": ["a/b"]}]}',
            "invalid_driver_descriptor",
        ),
        (
            '{"drivers": [{"driver_id": null, "capabilities": []}]}',
            "invalid_driver_descriptor",
        ),
        (
            '{"drivers": [{"driver_id": false, "capabilities": []}]}',
            "invalid_driver_descriptor",
        ),
        (
            '{"drivers": [{"driver_id": " ", "capabilities": []}]}',
            "invalid_driver_descriptor",
        ),
        (
            '{"drivers": [{"driver_id": "a/b", "capabilities": []}]}',
            "invalid_driver_descriptor",
        ),
        (
            '{"drivers": [{"driver_id": "example.driver", '
            '"capabilities": ["a", "a"]}]}',
            "duplicate_driver_capability",
        ),
        (
            '{"drivers": [{"driver_id": "example.driver", "capabilities": []}, '
            '{"driver_id": "example.driver", "capabilities": []}]}',
            "duplicate_driver_descriptor",
        ),
        ('{"drivers": NaN}', "invalid_support_metadata"),
        ('{"drivers": Infinity}', "invalid_support_metadata"),
        ('{"drivers": -Infinity}', "invalid_support_metadata"),
        ('{"drivers": 1e9999}', "invalid_support_metadata"),
        ('{"drivers": 1.5}', "invalid_support_metadata"),
        ('{"drivers": 123}', "invalid_support_metadata"),
        ('{"drivers": ' + "9" * 5000 + "}", "invalid_support_metadata"),
        ('{"drivers": []} trailing', "invalid_support_metadata"),
    ],
)
def test_strict_local_support_json_never_echoes_contents(tmp_path, text, code):
    resources = write(tmp_path, [managed(), provider(), binding()])
    support = tmp_path / "metadata.json"
    support.write_text(text, encoding="utf-8")
    error = failure(
        invoke("VirtualMachine/app", resources, phase="provision", support=support),
        code,
    )
    assert str(support) in error
    assert "never-echo-this" not in error
    assert "example.driver" not in error  # Adapter errors never echo file contents.


@pytest.mark.parametrize(
    "condition,code",
    [
        ("missing", "support_metadata_read_error"),
        ("directory", "support_metadata_read_error"),
        ("encoding", "support_metadata_decode_error"),
    ],
)
def test_local_metadata_io_and_decoding_errors(tmp_path, condition, code):
    path = write(tmp_path, [managed(), provider(), binding()])
    support = tmp_path / "bad.json"
    if condition == "directory":
        support.mkdir()
    if condition == "encoding":
        support.write_bytes(b"\xff\xfe")
    failure(
        invoke("VirtualMachine/app", path, phase="provision", support=support), code
    )


def test_local_metadata_is_explicit_only_and_driver_order_does_not_matter(tmp_path):
    path = write(tmp_path, [managed(), provider(), binding()])
    drivers = [
        {"driver_id": "unrelated.driver", "capabilities": []},
        {
            "driver_id": "example.driver",
            "capabilities": ["virtual_machine.observe", CAPABILITY],
        },
    ]
    support = support_file(tmp_path, drivers)
    before = success(
        invoke("VirtualMachine/app", path, phase="provision", support=support)
    )
    support_file(tmp_path, list(reversed(drivers)))
    assert (
        success(invoke("VirtualMachine/app", path, phase="provision", support=support))
        == before
    )
    # The nearby support.json is not implicitly discovered.
    failure(
        invoke("VirtualMachine/app", path, phase="provision"),
        "missing_driver_support_metadata",
    )


@pytest.mark.parametrize("length", [1, 2, 4])
def test_cycles_anywhere_fail_with_complete_directed_witness_before_output(
    tmp_path, length
):
    cyclic = [
        stage(f"s{i}", depends_on=[f"Stage/s{(i - 1) % length}"]) for i in range(length)
    ]
    path = write(tmp_path, [vm(), *cyclic])
    error = failure(invoke("VirtualMachine/app", path), "dependency_cycle")
    witness = " -> ".join([*(f"Stage/s{i}" for i in range(length)), "Stage/s0"])
    assert witness in error
    assert error.count("explicit: owner=Stage/") == length
    assert "field=depends_on[0]" in error
    assert str(path) in error and "root line" in error


@pytest.mark.parametrize("indirect", [False, True])
def test_stage_conflicts_include_path_assignments_and_all_origins(tmp_path, indirect):
    documents = [
        stage("early", 10),
        stage("late", 40),
        vm("late", lifecycle={"stage": "late"}),
    ]
    if indirect:
        documents.append(vm("middle", depends_on=["VirtualMachine/late"]))
    documents.append(
        vm(
            "early",
            lifecycle={"stage": "early"},
            depends_on=["VirtualMachine/middle" if indirect else "VirtualMachine/late"],
        )
    )
    path = write(tmp_path, documents)
    error = failure(invoke("Stage/early", path), "stage_order_conflict")
    witness = (
        "VirtualMachine/late -> "
        + ("VirtualMachine/middle -> " if indirect else "")
        + "VirtualMachine/early"
    )
    assert witness in error
    assert "Stage/early (order=10) field=lifecycle.stage" in error
    assert "Stage/late (order=40) field=lifecycle.stage" in error
    assert "explicit: owner=VirtualMachine/early field=depends_on[0]" in error
    assert "Sources (document roots)" in error
    assert str(path) in error


def test_implicit_stage_conflict_and_dependency_cycle_precedence(tmp_path):
    machine = vm(lifecycle={"stage": "early"})
    machine["spec"]["interfaces"] = [{"name": "main", "network": "Network/servers"}]
    net = network()
    net["lifecycle"] = {"stage": "late"}
    documents = [stage("early", 10), stage("late", 40), net, machine]
    path = write(tmp_path, documents)
    error = failure(invoke("VirtualMachine/app", path), "stage_order_conflict")
    assert "Network/servers -> VirtualMachine/app" in error
    assert (
        "implicit: owner=VirtualMachine/app field=spec.interfaces[0].network" in error
    )
    # A separate dependency-only cycle still fails first, before Stage analysis.
    path = write(tmp_path, [*documents, stage("cycle", depends_on=["Stage/cycle"])])
    error = failure(invoke("VirtualMachine/app", path), "dependency_cycle")
    assert "stage_order_conflict" not in error


@pytest.mark.parametrize(
    "condition,code",
    [
        ("yaml", "invalid_yaml"),
        ("duplicate-key", "duplicate_key"),
        ("unsafe", "invalid_yaml"),
        ("missing-file", "read_error"),
        ("encoding", "decode_error"),
        ("duplicate-resource", "duplicate_identity"),
        ("api", "invalid_resource"),
        ("kind", "invalid_resource"),
        ("spec", "invalid_resource"),
        ("reference", "missing_reference"),
        ("typed-reference", "invalid_resource"),
        ("gateway", "gateway_outside_subnet"),
        ("provider-target", "missing_binding_provider"),
    ],
)
def test_existing_compiler_failures_remain_actionable_without_partial_output(
    tmp_path, condition, code
):
    documents = [vm()]
    if condition == "duplicate-resource":
        documents += [vm()]
    elif condition == "api":
        documents[0]["api_version"] = "iac/v999"
    elif condition == "kind":
        documents[0]["kind"] = "Unknown"
    elif condition == "spec":
        documents[0]["spec"]["cpu"]["cores"] = "1"
    elif condition == "reference":
        documents[0]["depends_on"] = ["Stage/missing"]
    elif condition == "typed-reference":
        documents[0]["spec"]["placement"] = {"target": "Network/servers"}
    elif condition == "gateway":
        bad = network()
        bad["spec"]["ipv4"]["gateway"] = "198.51.100.1"
        documents += [bad]
    elif condition == "provider-target":
        documents += [binding()]
    path = write(tmp_path, documents)
    if condition in ("yaml", "duplicate-key", "unsafe"):
        path.write_text(
            {
                "yaml": "kind: [",
                "duplicate-key": "kind: Stage\nkind: Stage",
                "unsafe": 'payload: !!python/object/apply:os.system ["never-run"]',
            }[condition]
        )
    elif condition == "encoding":
        path.write_bytes(b"\xff")
    elif condition == "missing-file":
        path = tmp_path / "missing.yml"
    error = failure(invoke("VirtualMachine/app", path), code)
    assert str(path) in error
    if condition == "duplicate-resource":
        assert "first declaration:" in error and "document 2" in error
    if condition == "reference":
        assert "target=Stage/missing" in error
    if condition == "provider-target":
        assert "ProviderBinding/primary" in error and "Provider/primary" in error


def test_multifile_forward_references_permutations_and_renamed_layout(tmp_path):
    machine = managed()
    machine["lifecycle"]["stage"] = "workloads"
    machine["spec"]["interfaces"] = [{"name": "main", "network": "Network/servers"}]
    documents = [machine, binding(), provider(), network(), stage()]
    combined = write(tmp_path, documents)
    directory = tmp_path / "renamed"
    directory.mkdir()
    paths = [
        write(directory, [document], f"{i}.yml")
        for i, document in enumerate(reversed(documents))
    ]
    support = support_file(tmp_path)
    for phase in (None, "provision"):
        outputs = [
            success(
                invoke(
                    "VirtualMachine/app",
                    *files,
                    phase=phase,
                    support=support if phase else None,
                )
            )
            for files in ([combined], paths, list(reversed(paths)))
        ]
        assert len(set(outputs)) == 1
        assert str(tmp_path) not in outputs[0]


def test_bracket_identities_and_paths_render_literally_on_both_streams(tmp_path):
    name = "[red]app[bold]"
    path = write(tmp_path, [vm(name)], "[cyan]resources.yml")
    output = success(invoke(f"VirtualMachine/{name}", path, columns=20))
    assert f"Resource: VirtualMachine/{name}" in output
    assert "\x1b[" not in output
    error = failure(
        invoke("VirtualMachine/[blue]missing", path), "unknown_explain_resource"
    )
    assert "VirtualMachine/[blue]missing" in error
    path = write(
        tmp_path, [vm(name, depends_on=["Stage/[blue]missing"])], "[cyan]bad.yml"
    )
    error = failure(invoke(f"VirtualMachine/{name}", path), "missing_reference")
    assert str(path) in error and "Stage/[blue]missing" in error
    assert "\x1b[" not in error


def test_no_files_written_no_executable_config_or_environment_discovery(tmp_path):
    resource = managed()
    engine = provider(driver="not.installed.driver")
    marker = tmp_path / "must-not-exist"
    engine["spec"]["config"] = {
        "secret_ref": f"$(touch {marker})",
        "executable": str(marker),
        "endpoint": "invalid-offline-placeholder",
    }
    resource["extensions"] = {"example": {"opaque": "must-not-display"}}
    path = write(tmp_path, [resource, engine, binding()])
    support = support_file(
        tmp_path, [{"driver_id": "not.installed.driver", "capabilities": [CAPABILITY]}]
    )
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    for phase in (None, "provision"):
        output = success(
            invoke(
                "VirtualMachine/app",
                path,
                phase=phase,
                support=support if phase else None,
            )
        )
        assert "must-not-display" not in output and "secret_ref" not in output
    assert not marker.exists()
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


def test_help_version_and_byte_exact_existing_cli_outputs(tmp_path):
    path = write(tmp_path, [vm()])
    validate = runner.invoke(app, ["validate", str(path)])
    assert (
        success(validate) == "Validated 1 resource; resolved 0 declared references.\n"
    )
    graph = runner.invoke(app, ["graph", str(path)])
    assert (
        success(graph)
        == """Logical dependency graph (offline, not an execution plan)
Resources: 1; dependency edges: 0; declared reasons: 0; Stage assignments: 0

Vertices (1):
  VirtualMachine/app

Dependencies (0):
  (none)

Stage assignments (0):
  (none)

Topological order (1):
  1. VirtualMachine/app
"""
    )
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    visible_help = Text.from_ansi(help_result.stdout).plain
    assert all(command in visible_help for command in ("validate", "graph", "explain"))
    explain_help = runner.invoke(app, ["explain", "--help"])
    assert explain_help.exit_code == 0
    registered = get_command(app).commands["explain"]
    options = {option for parameter in registered.params for option in parameter.opts}
    assert {"--support-metadata", "--phase"} <= options
    version = runner.invoke(app, ["--version"])
    assert (
        Text.from_ansi(success(version)).plain == f"Diatonic Orchestrator {__version__}"
    )
    assert version.stdout.endswith("\n")


MANAGED_TAIL = """Offline phase analysis:
  Requested phase: provision
  Ownership: managed
  Declaration origin: declared
  Required capability: virtual_machine.provision

Provider resolution: selected (offline declared support only)
  ProviderBinding: ProviderBinding/lab-vm-provision
  Provider: Provider/primary
  Driver: example.driver
  Priority: 100

Candidates (1):
  ProviderBinding/lab-vm-provision: selected
    provider=Provider/primary; priority=100; capability=virtual_machine.provision
    driver=example.driver; support=declared_supported
    selected_highest_priority: field=spec.priority
"""


@pytest.mark.parametrize("columns", [20, 160])
def test_readme_examples_and_exact_managed_presentation(columns):
    resources = ROOT / "examples/offline-resolution/resources.yml"
    support = ROOT / "examples/offline-resolution/driver-support.json"
    baseline = success(invoke("VirtualMachine/app", resources, columns=columns))
    assert baseline.endswith("Provider resolution: not requested\n")
    assert "lifecycle.phases.provision: managed" in baseline
    output = success(
        invoke(
            "VirtualMachine/app",
            resources,
            phase="provision",
            support=support,
            columns=columns,
        )
    )
    assert output.endswith(MANAGED_TAIL)
    assert str(resources) not in output and str(support) not in output


def test_candidate_diagnostics_render_literals_and_are_width_independent(tmp_path):
    resource = managed(
        metadata={"name": "[red]app", "labels": {"site": "[bold]literal"}}
    )
    path = write(
        tmp_path,
        [
            resource,
            provider("[blue]primary"),
            binding(
                "[green]candidate", target="[blue]primary", labels={"site": "other"}
            ),
        ],
        "[yellow]resources.yml",
    )
    errors = [
        failure(
            invoke("VirtualMachine/[red]app", path, phase="provision", columns=width),
            "no_matching_provider_binding",
        )
        for width in (20, 160)
    ]
    assert errors[0] == errors[1]
    assert "ProviderBinding/[green]candidate" in errors[0]
    assert "Provider/[blue]primary" in errors[0]
    assert "actual='[bold]literal'" in errors[0]
    assert str(path) in errors[0]
    metadata = tmp_path / "[red]support.json"
    metadata.write_text('{"drivers":[],"drivers":[]}')
    error = failure(
        invoke("VirtualMachine/[red]app", path, phase="provision", support=metadata),
        "invalid_support_metadata",
    )
    assert str(metadata) in error


def test_deeply_nested_support_json_is_a_controlled_local_error(tmp_path):
    path = write(tmp_path, [managed(), provider(), binding()])
    support = tmp_path / "deep.json"
    support.write_text("[" * 2000 + "]" * 2000)
    failure(
        invoke("VirtualMachine/app", path, phase="provision", support=support),
        "invalid_support_metadata",
    )


@pytest.mark.parametrize("columns", [80, 160])
@pytest.mark.parametrize("force_color", [None, "1"])
def test_explain_help_options_render_with_or_without_ansi(columns, force_color):
    result = runner.invoke(
        app,
        ["explain", "--help"],
        env={"COLUMNS": str(columns), "FORCE_COLOR": force_color, "NO_COLOR": ""},
    )
    assert result.exit_code == 0
    assert result.stderr == ""
    # Rich styles pieces of a flag independently; raw ANSI output is not a token.
    visible = Text.from_ansi(result.stdout).plain
    assert "--support-metadata" in visible
    assert "--phase" in visible
