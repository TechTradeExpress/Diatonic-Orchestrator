"""CLI stream/exit behavior and integration with the authoritative compiler."""

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

import diatonic.cli as cli
from diatonic.compiler.normalize import NormalizationError
from diatonic.compiler.references import SourceLocation

ROOT = Path(__file__).parents[1]
EXAMPLE = ROOT / "examples/infrastructure/resources.yml"
STAGES = ROOT / "tests/fixtures/reference-stages.yml"
runner = CliRunner()


def stage(name: str = "workloads", **overrides: Any) -> dict[str, Any]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": "Stage",
        "metadata": {"name": name},
        "spec": {"order": 40},
        **overrides,
    }


def vm(**overrides: Any) -> dict[str, Any]:
    return {
        "api_version": "iac/v0alpha1",
        "kind": "VirtualMachine",
        "metadata": {"name": "app"},
        "spec": {"cpu": {"cores": 1}, "memory": {"mib": 512}},
        **overrides,
    }


def write(tmp_path: Path, text: str, name: str = "input.yml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def write_resource(tmp_path: Path, resource: dict[str, Any], name: str = "input.yml"):
    return write(tmp_path, yaml.safe_dump(resource, sort_keys=False), name)


def assert_failure(result, code: str) -> str:
    assert result.exit_code == 1
    assert result.stdout == ""
    assert code in result.stderr
    assert "Validated" not in result.stderr
    assert "Traceback" not in result.output
    return result.stderr


def test_single_stage_success_stdout_and_stderr(tmp_path: Path) -> None:
    path = write_resource(tmp_path, stage())
    result = runner.invoke(cli.app, ["validate", str(path)])
    assert result.exit_code == 0
    assert result.stdout == "Validated 1 resource; resolved 0 declared references.\n"
    assert result.stderr == ""


def test_multiple_files_and_multidocument_stream(tmp_path: Path) -> None:
    first = write(
        tmp_path,
        yaml.safe_dump(stage("platform"))
        + "---\n"
        + yaml.safe_dump(stage("workloads")),
        "stages.yml",
    )
    second = write_resource(tmp_path, vm(lifecycle={"stage": "workloads"}), "vm.yml")
    result = runner.invoke(cli.app, ["validate", str(second), str(first)])
    assert result.exit_code == 0
    assert result.stdout == "Validated 3 resources; resolved 1 declared reference.\n"
    assert result.stderr == ""


def test_full_infrastructure_example_requires_explicit_stages() -> None:
    valid = runner.invoke(cli.app, ["validate", str(EXAMPLE), str(STAGES)])
    assert valid.exit_code == 0
    assert valid.stdout == "Validated 6 resources; resolved 5 declared references.\n"
    assert valid.stderr == ""
    text = assert_failure(
        runner.invoke(cli.app, ["validate", str(EXAMPLE)]), "missing_reference"
    )
    assert "Stage/platform" in text
    assert "Hypervisor/host01" in text
    assert "field=lifecycle.stage" in text
    assert "document 2" in text


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("value: [", "invalid_yaml"),
        ("x: 1\nx: 2", "duplicate_key"),
        ("spec:\n  cpu:\n    cores: 1\n    cores: 2", "duplicate_key"),
        ("value: !!python/object/apply:os.system ['false']", "invalid_yaml"),
        ("value: !custom text", "invalid_yaml"),
        ("", "empty_document"),
        ("null", "empty_document"),
        ("[]", "invalid_root"),
        ("<<: {a: 1}", "merge_not_allowed"),
        ("x: &x 1\ny: *x", "alias_not_allowed"),
    ],
)
def test_yaml_errors_are_controlled_and_source_aware(
    tmp_path: Path, text: str, code: str
):
    path = write(tmp_path, text)
    output = assert_failure(runner.invoke(cli.app, ["validate", str(path)]), code)
    assert str(path) in output
    assert "document 1" in output


def test_yaml_duplicate_key_keeps_parser_problem_mark(tmp_path: Path) -> None:
    path = write(tmp_path, "# comment\nx: 1\nx: 2\n")
    output = assert_failure(
        runner.invoke(cli.app, ["validate", str(path)]), "duplicate_key"
    )
    assert f"{path}:3:1" in output


@pytest.mark.parametrize("case", ["missing", "directory", "decode"])
def test_file_failures_use_exit_one(tmp_path: Path, case: str) -> None:
    path = tmp_path / "input.yml"
    code = "read_error"
    if case == "directory":
        path = tmp_path
    elif case == "decode":
        path.write_bytes(b"bad: \xff\n")
        code = "decode_error"
    output = assert_failure(runner.invoke(cli.app, ["validate", str(path)]), code)
    assert str(path) in output
    assert "root line" not in output


@pytest.mark.parametrize(
    ("resource", "field", "schema_code"),
    [
        (stage(kind="Unknown"), "kind", "union_tag_invalid"),
        (stage(api_version="iac/v0alpha2"), "api_version", "literal_error"),
        (
            vm(spec={"cpu": {"cores": "4"}, "memory": {"mib": 1}}),
            "spec.cpu.cores",
            "int_type",
        ),
        (vm(spec={"cpu": [], "memory": {"mib": 1}}), "spec.cpu", "model_type"),
        (stage(unexpected=True), "unexpected", "extra_forbidden"),
    ],
)
def test_schema_errors_include_owner_field_code_and_root_location(
    tmp_path: Path,
    resource: dict[str, Any],
    field: str,
    schema_code: str,
) -> None:
    path = write(tmp_path, "# comment\n---\n" + yaml.safe_dump(resource))
    output = assert_failure(
        runner.invoke(cli.app, ["validate", str(path)]), "invalid_resource"
    )
    assert str(path) in output
    assert "document 1, root line 3, column 1" in output
    assert f"field={field}" in output
    assert f"schema={schema_code}" in output
    assert f"resource={resource['kind']}/{resource['metadata']['name']}" in output


def test_duplicate_identity_reports_both_file_origins(tmp_path: Path) -> None:
    first = write_resource(tmp_path, stage(), "first.yml")
    second = write(tmp_path, "# comment\n" + yaml.safe_dump(stage()), "second.yml")
    output = assert_failure(
        runner.invoke(cli.app, ["validate", str(first), str(second)]),
        "duplicate_identity",
    )
    assert f"{second} (document 1, root line 2, column 1)" in output
    assert f"first declaration: {first} (document 1, root line 1, column 1)" in output
    assert "resource=Stage/workloads" in output


def test_duplicate_identity_within_stream(tmp_path: Path) -> None:
    path = write(tmp_path, yaml.safe_dump(stage()) + "---\n" + yaml.safe_dump(stage()))
    output = assert_failure(
        runner.invoke(cli.app, ["validate", str(path)]), "duplicate_identity"
    )
    assert "document 2" in output
    assert "first declaration:" in output
    assert "document 1" in output


@pytest.mark.parametrize(
    ("fields", "path", "target"),
    [
        ({"depends_on": ["Network/missing"]}, "depends_on[0]", "Network/missing"),
        ({"lifecycle": {"stage": "missing"}}, "lifecycle.stage", "Stage/missing"),
        (
            {"placement": {"target": "Hypervisor/missing"}},
            "spec.placement.target",
            "Hypervisor/missing",
        ),
        (
            {"interfaces": [{"name": "main", "network": "Network/missing"}]},
            "spec.interfaces[0].network",
            "Network/missing",
        ),
        ({"image": {"ref": "Image/missing"}}, "spec.image.ref", "Image/missing"),
    ],
)
def test_missing_declared_references_are_actionable(
    tmp_path: Path,
    fields: dict[str, Any],
    path: str,
    target: str,
) -> None:
    resource = vm()
    if path.startswith("spec."):
        resource["spec"].update(fields)
    else:
        resource.update(fields)
    source = write_resource(tmp_path, resource)
    output = assert_failure(
        runner.invoke(cli.app, ["validate", str(source)]), "missing_reference"
    )
    assert f"field={path}" in output
    assert f"target={target}" in output
    assert "resource=VirtualMachine/app" in output
    assert "document 1, root line 1, column 1" in output


def test_wrong_kind_reference_is_schema_failure(tmp_path: Path) -> None:
    resource = vm()
    resource["spec"]["image"] = {"ref": "Network/wrong"}
    source = write_resource(tmp_path, resource)
    output = assert_failure(
        runner.invoke(cli.app, ["validate", str(source)]), "invalid_resource"
    )
    assert "field=spec.image.ref" in output
    assert "reference must target Image/name" in output


@pytest.mark.parametrize(
    "args",
    [["validate"], ["validate", "--unknown"], ["validate", "input.yml", "--unknown"]],
)
def test_usage_errors_are_exit_two(args: list[str]) -> None:
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 2
    assert "Usage:" in result.stderr
    assert "Validated" not in result.stdout


@pytest.mark.parametrize("args", [["--help"], ["--version"], ["validate", "--help"]])
def test_help_and_version_compatibility(args: list[str]) -> None:
    result = runner.invoke(cli.app, args)
    assert result.exit_code == 0
    assert result.stderr == ""
    if args == ["validate", "--help"]:
        assert "FILE" in result.stdout
        assert "schemas" in result.stdout
    else:
        assert "Diatonic Orchestrator" in result.stdout


def test_normalization_error_is_presented_without_traceback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = write_resource(tmp_path, stage())

    def inconsistent(index):
        origin = SourceLocation(source, 1, 1, 1)
        raise NormalizationError("Stage/workloads", "Stage/changed", origin)

    monkeypatch.setattr(cli, "normalize_resources", inconsistent)
    output = assert_failure(
        runner.invoke(cli.app, ["validate", str(source)]), "identity_mismatch"
    )
    assert "Stage/workloads" in output
    assert "Stage/changed" in output
    assert "document 1, root line 1, column 1" in output


def test_untrusted_diagnostic_brackets_are_literal(tmp_path: Path) -> None:
    path = write_resource(
        tmp_path,
        stage("[red]owner", depends_on=["Stage/[bold]missing"]),
        "[bold]input.yml",
    )
    output = assert_failure(
        runner.invoke(cli.app, ["validate", str(path)]), "missing_reference"
    )
    assert str(path) in output
    assert "Stage/[red]owner" in output
    assert "Stage/[bold]missing" in output


@pytest.mark.parametrize("valid", [True, False])
def test_no_source_modification_or_generated_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    valid: bool,
) -> None:
    monkeypatch.chdir(tmp_path)
    path = write_resource(tmp_path, stage() if valid else stage(api_version="bad"))
    before = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    result = runner.invoke(cli.app, ["validate", path.name])
    assert result.exit_code == (0 if valid else 1)
    after = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in tmp_path.rglob("*")
        if p.is_file()
    }
    assert after == before


def test_no_ambient_failure_state_and_no_new_cycle_semantics(tmp_path: Path) -> None:
    invalid = write_resource(tmp_path, stage(api_version="bad"), "bad.yml")
    valid = write_resource(tmp_path, stage(depends_on=["Stage/workloads"]), "good.yml")
    assert_failure(
        runner.invoke(cli.app, ["validate", str(invalid)]), "invalid_resource"
    )
    result = runner.invoke(cli.app, ["validate", str(valid)])
    assert result.exit_code == 0
    assert result.stderr == ""
    assert "resolved 1 declared reference." in result.stdout
