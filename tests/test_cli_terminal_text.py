"""Untrusted terminal controls stay visible data, independently of Rich markup."""

import json

import pytest
import yaml
from typer.testing import CliRunner

from diatonic.cli import app
from diatonic.cli_text import terminal_lines, terminal_text
from diatonic.compiler.loader import load_yaml_files
from diatonic.compiler.references import resolve_resources

runner = CliRunner()
PAYLOAD = "[red]demo\x1b[31m\x07\x08\x7f\x80\x9b31m\\x1b"
DISPLAY = r"[red]demo\x1b[31m\x07\x08\x7f\x80\x9b31m\\x1b"
ENVIRONMENTS = [
    {"NO_COLOR": "1", "TERM": "dumb", "FORCE_COLOR": None},
    {"NO_COLOR": None, "TERM": "xterm-256color", "FORCE_COLOR": "1"},
]


def stage(name=PAYLOAD, order=10, **fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": name},
        "spec": {"order": order},
        **fields,
    }


def vm(**fields):
    return {
        "api_version": "iac/v0alpha1",
        "kind": "VirtualMachine",
        "metadata": {"name": PAYLOAD},
        "spec": {"cpu": {"cores": 1}, "memory": {"mib": 512}},
        "lifecycle": {"phases": {"provision": "managed"}},
        **fields,
    }


def write(tmp_path, *documents, name="resources.yml"):
    path = tmp_path / name
    path.write_text(yaml.safe_dump_all(documents, sort_keys=False), encoding="utf-8")
    return path


def invoke(command, path, *, identity=None, extra=(), env=None):
    args = [command]
    if command == "explain":
        args.append(identity or f"Stage/{PAYLOAD}")
    return runner.invoke(app, [*args, str(path), *extra], env=env)


def assert_no_untrusted_controls(output):
    # Newlines are the CLI's own layout. No other C0, DEL or C1 is permitted.
    assert not any(
        (ord(char) < 0x20 and char != "\n") or 0x7F <= ord(char) <= 0x9F
        for char in output
    ), repr(output)


@pytest.mark.parametrize("codepoint", [*range(32), *range(127, 160)])
def test_complete_control_ranges_are_escaped(codepoint):
    assert terminal_text(chr(codepoint)) == f"\\x{codepoint:02x}"


def test_escape_policy_is_unambiguous_and_keeps_printable_unicode_and_markup():
    assert terminal_text("\x1b[31m\\x1b[31m [red]café[/red]") == (
        r"\x1b[31m\\x1b[31m [red]café[/red]"
    )
    assert terminal_lines(["heading", "value=a\n\tb\r", "", "end"]) == (
        "heading\nvalue=a\\x0a\\x09b\\x0d\n\nend"
    )


@pytest.mark.parametrize("env", ENVIRONMENTS)
@pytest.mark.parametrize("command", ["validate", "graph", "explain"])
def test_success_escapes_controls_without_changing_identity_or_layout(
    tmp_path, command, env
):
    path = write(tmp_path, stage())
    index = resolve_resources(load_yaml_files([path]))
    assert tuple(index.resources) == (f"Stage/{PAYLOAD}",)
    result = invoke(command, path, env=env)
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert_no_untrusted_controls(result.stdout)
    if command == "validate":
        assert (
            result.stdout == "Validated 1 resource; resolved 0 declared references.\n"
        )
    else:
        assert f"Stage/{DISPLAY}" in result.stdout
        assert "\n\n" in result.stdout  # Trusted section breaks remain intact.


def test_graph_keeps_raw_sorting_and_distinguishes_literal_escape_names(tmp_path):
    path = write(tmp_path, stage("\\x01"), stage("\x01"))
    result = invoke("graph", path)
    assert result.exit_code == 0
    assert "Vertices (2):\n  Stage/\\x01\n  Stage/\\\\x01\n" in result.stdout
    assert "1. Stage/\\x01\n  2. Stage/\\\\x01\n" in result.stdout
    assert tuple(resolve_resources(load_yaml_files([path])).resources) == (
        "Stage/\\x01",
        "Stage/\x01",
    )


@pytest.mark.parametrize("command", ["validate", "graph", "explain"])
@pytest.mark.parametrize("env", ENVIRONMENTS)
@pytest.mark.parametrize("scenario", ["missing", "duplicate", "schema", "binding"])
def test_declaration_diagnostics_escape_owner_target_field_and_path(
    tmp_path, command, scenario, env
):
    if scenario == "missing":
        docs = [stage(depends_on=[f"Stage/{PAYLOAD}missing"])]
        code = "missing_reference"
    elif scenario == "duplicate":
        docs = [stage(), stage()]
        code = "duplicate_identity"
    elif scenario == "schema":
        docs = [stage(**{PAYLOAD + "\n\t": 1})]
        code = "invalid_resource"
    else:
        docs = [
            {
                "api_version": "iac/v0alpha1",
                "kind": "ProviderBinding",
                "metadata": {"name": PAYLOAD},
                "spec": {
                    "capability": "virtual_machine.provision",
                    "priority": 1,
                    "match": {"kind": "VirtualMachine"},
                    "provider": f"Provider/{PAYLOAD}",
                },
            }
        ]
        code = "missing_binding_provider"
    path = write(tmp_path, *docs, name=PAYLOAD + "\n\t\r.yml")
    result = invoke(command, path, env=env)
    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    assert code in result.stderr
    assert DISPLAY in result.stderr
    assert DISPLAY + r"\x0a\x09\x0d.yml" in result.stderr
    assert len(result.stderr.splitlines()) == 1
    assert_no_untrusted_controls(result.stderr)


@pytest.mark.parametrize("command", ["validate", "graph", "explain"])
@pytest.mark.parametrize("scenario", ["missing", "decode", "yaml"])
def test_file_and_parser_diagnostics_preserve_escaped_source(
    tmp_path, command, scenario
):
    path = tmp_path / (PAYLOAD + "\n.yml")
    code = "read_error"
    if scenario == "decode":
        path.write_bytes(b"\xff")
        code = "decode_error"
    elif scenario == "yaml":
        path.write_text("value: [", encoding="utf-8")
        code = "invalid_yaml"
    result = invoke(command, path)
    assert result.exit_code == 1
    assert result.stdout == ""
    assert code in result.stderr
    assert DISPLAY + r"\x0a.yml" in result.stderr
    assert len(result.stderr.splitlines()) == 1
    assert_no_untrusted_controls(result.stderr)


@pytest.mark.parametrize("command", ["graph", "explain"])
@pytest.mark.parametrize("conflict", ["cycle", "stage"])
def test_graph_diagnostics_escape_witness_edges_assignments_and_sources(
    tmp_path, command, conflict
):
    if conflict == "cycle":
        docs = [stage(depends_on=[f"Stage/{PAYLOAD}"])]
        code = "dependency_cycle"
    else:
        docs = [
            stage("early", 1),
            stage("late", 2),
            stage(lifecycle={"stage": "early"}, depends_on=["Stage/late-member"]),
            stage("late-member", lifecycle={"stage": "late"}),
        ]
        code = "stage_order_conflict"
    path = write(tmp_path, *docs, name=PAYLOAD + "\n.yml")
    result = invoke(command, path)
    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    assert code in result.stderr
    assert f"Stage/{DISPLAY}" in result.stderr
    assert DISPLAY + r"\x0a.yml" in result.stderr
    assert "\nSources (document roots):\n" in result.stderr
    assert_no_untrusted_controls(result.stderr)


def test_unknown_explicit_explain_identity_is_escaped(tmp_path):
    path = write(tmp_path, stage("other"))
    result = invoke("explain", path)
    assert result.exit_code == 1
    assert f"unknown_explain_resource: resource=Stage/{DISPLAY}" in result.stderr
    assert_no_untrusted_controls(result.output)


def test_phase_analysis_error_is_escaped(tmp_path):
    path = write(tmp_path, stage(lifecycle={"phases": {"provision": "managed"}}))
    result = invoke("explain", path, extra=["--phase", "provision"])
    assert result.exit_code == 1
    assert "unsupported_managed_phase" in result.stderr
    assert f"Stage/{DISPLAY}" in result.stderr
    assert_no_untrusted_controls(result.output)


@pytest.mark.parametrize("scenario", ["selected", "missing-support", "bad-support"])
def test_phase_selection_and_errors_escape_candidates_driver_and_sources(
    tmp_path, scenario
):
    capability = "virtual_machine.provision"
    provider = {
        "api_version": "iac/v0alpha1",
        "kind": "Provider",
        "metadata": {"name": PAYLOAD},
        "spec": {"driver": PAYLOAD, "config": {}},
    }
    binding = {
        "api_version": "iac/v0alpha1",
        "kind": "ProviderBinding",
        "metadata": {"name": PAYLOAD},
        "spec": {
            "capability": capability,
            "priority": 1,
            "match": {"kind": "VirtualMachine"},
            "provider": f"Provider/{PAYLOAD}",
        },
    }
    path = write(tmp_path, vm(), provider, binding, name=PAYLOAD + "\n.yml")
    extra = ["--phase", "provision"]
    if scenario != "missing-support":
        support = tmp_path / (PAYLOAD + "\n.json")
        support.write_text(
            json.dumps(
                {"drivers": [{"driver_id": PAYLOAD, "capabilities": [capability]}]}
            )
            if scenario == "selected"
            else "{",
            encoding="utf-8",
        )
        extra += ["--support-metadata", str(support)]
    result = invoke("explain", path, identity=f"VirtualMachine/{PAYLOAD}", extra=extra)
    assert result.exit_code == (0 if scenario == "selected" else 1), result.output
    assert_no_untrusted_controls(result.output)
    if scenario == "selected":
        assert f"ProviderBinding: ProviderBinding/{DISPLAY}" in result.stdout
        assert f"Provider: Provider/{DISPLAY}" in result.stdout
        assert f"Driver: {DISPLAY}" in result.stdout
        assert result.stderr == ""
    else:
        assert result.stdout == ""
        assert DISPLAY in result.stderr
        assert (
            "invalid_support_metadata" in result.stderr
            if scenario == "bad-support"
            else ("missing_driver_support_metadata" in result.stderr)
        )


@pytest.mark.parametrize("env", ENVIRONMENTS[:1])
@pytest.mark.parametrize(
    "args",
    [
        ["bad\x1b[31m\x07\x9b"],
        ["--bad\x1b[31m\x07\x9b\n"],
        ["graph", "--bad\x1b[31m\x07\x9b\n"],
        ["explain", "Stage/a", "input.yml", "--phase", "bad\x1b[31m\x07\x9b\n"],
        ["explain", "bad\nidentity", "input.yml"],
    ],
)
def test_usage_errors_do_not_emit_untrusted_controls(args, env):
    result = runner.invoke(app, args, env=env)
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert "Usage:" in result.stderr
    assert_no_untrusted_controls(result.stderr)


@pytest.mark.parametrize("command", ["validate", "graph", "explain"])
def test_ipv4_semantic_diagnostic_escapes_both_network_and_owner(tmp_path, command):
    network = {
        "api_version": "iac/v0alpha1",
        "kind": "Network",
        "metadata": {"name": PAYLOAD},
        "spec": {
            "vlan_id": 1,
            "ipv4": {"cidr": "192.0.2.0/24", "gateway": "192.0.2.1"},
        },
    }
    resource = vm(
        spec={
            "cpu": {"cores": 1},
            "memory": {"mib": 512},
            "interfaces": [
                {
                    "name": "main",
                    "network": f"Network/{PAYLOAD}",
                    "ipv4": {"mode": "static", "address": "198.51.100.2/24"},
                }
            ],
        }
    )
    path = write(tmp_path, network, resource)
    result = invoke(command, path, identity=f"VirtualMachine/{PAYLOAD}")
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "outside" in result.stderr
    assert f"resource=VirtualMachine/{DISPLAY}" in result.stderr
    assert f"network=Network/{DISPLAY}" in result.stderr
    assert_no_untrusted_controls(result.stderr)


def test_dependency_edges_and_stage_lifecycle_fields_are_escaped(tmp_path):
    path = write(
        tmp_path,
        stage(),
        vm(lifecycle={"stage": PAYLOAD}, depends_on=[f"Stage/{PAYLOAD}"]),
    )
    for command in ("graph", "explain"):
        result = invoke(command, path, identity=f"VirtualMachine/{PAYLOAD}")
        assert result.exit_code == 0
        assert f"Stage/{DISPLAY} -> VirtualMachine/{DISPLAY}" in result.stdout
        if command == "explain":
            assert f"lifecycle.stage: {DISPLAY}" in result.stdout
        else:
            assert f"VirtualMachine/{DISPLAY} -> Stage/{DISPLAY}" in result.stdout
        assert_no_untrusted_controls(result.stdout)
