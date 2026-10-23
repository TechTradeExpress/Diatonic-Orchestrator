"""Strict loading, provenance, failure diagnostics and model handoff."""

from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest
import yaml

from diatonic.compiler.loader import (
    YamlLoadError,
    load_yaml_file,
    load_yaml_files,
)
from diatonic.model import Stage, VirtualMachine, parse_resource


def write_yaml(tmp_path: Path, text: str, name: str = "input.yml") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_multidocument_data_and_locations(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, "# comment\n---\nfirst: 1\n---\n# next\n  second: 2\n")
    documents = load_yaml_file(path)
    assert [d.data for d in documents] == [{"first": 1}, {"second": 2}]
    assert [d.source_path for d in documents] == [path, path]
    assert [d.document_index for d in documents] == [1, 2]
    assert [(d.line, d.column) for d in documents] == [(3, 1), (6, 3)]
    with pytest.raises(FrozenInstanceError):
        documents[0].line = 99  # type: ignore[misc]


def test_explicit_path_order_repeats_and_generator_input(tmp_path: Path) -> None:
    z = write_yaml(tmp_path, "z: 1\n---\nz: 2\n", "z.yml")
    a = write_yaml(tmp_path, "a: 3\n", "a.yaml")
    documents = load_yaml_files(path for path in [z, a, z])
    assert [d.data for d in documents] == [
        {"z": 1}, {"z": 2}, {"a": 3}, {"z": 1}, {"z": 2},
    ]
    assert [d.document_index for d in documents] == [1, 2, 1, 1, 2]
    assert load_yaml_files([]) == []


def test_raw_unknown_kind_and_version_are_not_semantically_validated(tmp_path: Path):
    path = write_yaml(
        tmp_path, "kind: FutureKind\napi_version: future/v9\nextra: true\n",
    )
    assert load_yaml_file(path)[0].data == {
        "kind": "FutureKind", "api_version": "future/v9", "extra": True,
    }


def test_existing_examples_handoff_to_models() -> None:
    root = Path(__file__).parents[1] / "examples" / "minimal"
    documents = load_yaml_files([root / "stages.yml", root / "resources.yml"])
    stage, vm = [parse_resource(d.data) for d in documents]
    assert isinstance(stage, Stage)
    assert stage.identity == "Stage/workloads"
    assert isinstance(vm, VirtualMachine)
    assert vm.spec.cpu.cores == 4
    assert vm.spec.memory.mib == 4096


@pytest.mark.parametrize(
    ("text", "line", "column"),
    [
        ("name: first\nname: second\n", 2, 1),
        ("spec:\n  cpu:\n    cores: 1\n    cores: 2\n", 4, 5),
        ("items:\n  - name: one\n    name: two\n", 3, 5),
        ('name: first\n"name": second\n', 2, 1),
        ('"a": first\n"\\x61": second\n', 2, 1),
    ],
)
def test_duplicate_keys_with_exact_location(
    tmp_path: Path, text: str, line: int, column: int,
) -> None:
    path = write_yaml(tmp_path, text)
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(path)
    error = exc.value
    assert error.code == "duplicate_key"
    assert error.source_path == path
    assert error.document_index == 1
    assert (error.line, error.column) == (line, column)
    assert "duplicate mapping key" in error.reason
    assert f"{path}:{line}:{column}" in str(error)


@pytest.mark.parametrize("key", ["1", "true", "null", "1.5", "[a, b]", "{a: b}"])
def test_non_string_keys_at_all_depths(tmp_path: Path, key: str) -> None:
    path = write_yaml(tmp_path, f"nested:\n  - {key}: value\n")
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(path)
    assert exc.value.code == "invalid_mapping_key"
    assert (exc.value.line, exc.value.column) == (2, 5)


@pytest.mark.parametrize("text", ["", "# only a comment\n", "---\n", "null\n", "~\n"])
def test_empty_stream_and_null_documents(tmp_path: Path, text: str) -> None:
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(write_yaml(tmp_path, text))
    assert exc.value.code == "empty_document"
    assert exc.value.document_index == 1


@pytest.mark.parametrize("text", ["42", "true", "hello", "[]", "- a\n- b", "!!set {a}"])
def test_invalid_root(tmp_path: Path, text: str) -> None:
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(write_yaml(tmp_path, text))
    assert exc.value.code == "invalid_root"


@pytest.mark.parametrize("tail", ["---\n", "---\nnull", "---\n# empty\n"])
def test_empty_later_documents_are_not_skipped(tmp_path: Path, tail: str) -> None:
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(write_yaml(tmp_path, "valid: 1\n" + tail))
    assert exc.value.code == "empty_document"
    assert exc.value.document_index == 2


@pytest.mark.parametrize(
    "text",
    [
        "value: [unterminated", "value: {missing: bracket", "value:\n\tbad: indent",
        "value: !custom x", "value: !!python/object:builtins.object {}",
        "value: !!python/object/apply:os.system ['false']", "value: \x00",
    ],
)
def test_malformed_yaml_and_unsupported_tags(tmp_path: Path, text: str) -> None:
    path = write_yaml(tmp_path, text)
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(path)
    assert exc.value.code == "invalid_yaml"
    assert exc.value.source_path == path
    assert exc.value.document_index == 1
    assert exc.value.reason


def test_error_in_second_document_has_correct_index_and_mark(tmp_path: Path) -> None:
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(write_yaml(tmp_path, "first: 1\n---\nx: 1\nx: 2\n"))
    assert exc.value.document_index == 2
    assert (exc.value.line, exc.value.column) == (4, 1)


def test_syntax_error_in_later_document_has_location(tmp_path: Path) -> None:
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(write_yaml(tmp_path, "first: 1\n---\nvalue: [\n"))
    assert exc.value.code == "invalid_yaml"
    assert exc.value.document_index == 2
    assert (exc.value.line, exc.value.column) == (4, 1)


@pytest.mark.parametrize("text", ["<<: {a: 1}", "a: 1\n<<: {a: 2}", "x:\n  <<: {}"])
def test_merge_keys_rejected_even_without_aliases(tmp_path: Path, text: str) -> None:
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(write_yaml(tmp_path, text))
    assert exc.value.code == "merge_not_allowed"


@pytest.mark.parametrize(
    "text",
    [
        "first: &x {a: 1}\nsecond: *x",  # ordinary alias
        "first: &x 1\nsecond: *x",  # scalar alias
        "first: &x [*x]",  # recursive sequence
        "first: &x {child: *x}",  # recursive mapping
        "first: *undefined",  # undefined alias
        "first: &x {a: 1}\nsecond: {<<: *x}",  # merge alias
        "a: &a [1, 2]\nb: &b [*a, *a]\nc: [*b, *b]",  # expansion
    ],
)
def test_aliases_rejected_before_construction(tmp_path: Path, text: str) -> None:
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(write_yaml(tmp_path, text))
    assert exc.value.code == "alias_not_allowed"
    assert exc.value.line is not None
    assert exc.value.column is not None


def test_unused_anchors_quoted_keys_and_empty_mapping_accepted(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, 'value: &unused 1\n"<<": 2\n"true": 3\n---\n{}\n')
    assert [d.data for d in load_yaml_file(path)] == [
        {"value": 1, "<<": 2, "true": 3}, {},
    ]


def test_safe_loader_retains_scalar_resolution_without_global_mutation(tmp_path: Path):
    path = write_yaml(tmp_path, "flag: yes\nwhen: 2026-10-23\nvalue: 2\n")
    assert load_yaml_file(path)[0].data == {
        "flag": True, "when": date(2026, 10, 23), "value": 2,
    }
    # The strict subclass must not change PyYAML's shared constructor registry.
    assert yaml.safe_load("x: 1\nx: 2") == {"x": 2}


@pytest.mark.parametrize(
    "scalar", ["!!int invalid", '!!int ""', "!!float invalid", "!!bool invalid",
               "!!timestamp invalid", "2026-99-99"],
)
def test_invalid_tagged_scalars_are_controlled_errors(tmp_path: Path, scalar: str):
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(write_yaml(tmp_path, f"value: {scalar}\n"))
    assert exc.value.code == "invalid_scalar"
    assert (exc.value.line, exc.value.column) == (1, 8)


def test_utf8_bom_and_unicode(tmp_path: Path) -> None:
    path = write_yaml(tmp_path, '\ufeffname: "żółw"\n')
    assert load_yaml_file(str(path))[0].data == {"name": "żółw"}


def test_malformed_encoding(tmp_path: Path) -> None:
    path = tmp_path / "bad.yml"
    path.write_bytes(b"name: \xff\n")
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(path)
    assert exc.value.code == "decode_error"
    assert exc.value.source_path == path
    assert exc.value.document_index is None
    assert exc.value.line is None


def test_missing_file_and_directory(tmp_path: Path) -> None:
    for path in [tmp_path / "missing.yml", tmp_path]:
        with pytest.raises(YamlLoadError) as exc:
            load_yaml_file(path)
        assert exc.value.code == "read_error"
        assert exc.value.source_path == path
        assert exc.value.document_index is None
        assert exc.value.line is None


def test_permission_failure_is_wrapped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "denied.yml"

    def denied(*args: object, **kwargs: object) -> str:
        raise PermissionError("permission denied")

    monkeypatch.setattr(Path, "read_text", denied)
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(path)
    assert exc.value.code == "read_error"
    assert exc.value.source_path == path
    assert "permission denied" in exc.value.reason


def test_relative_source_path_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    write_yaml(tmp_path, "value: 1")
    monkeypatch.chdir(tmp_path)
    assert load_yaml_file("input.yml")[0].source_path == Path("input.yml")


def test_multifile_failure_identifies_failing_file(tmp_path: Path) -> None:
    first = write_yaml(tmp_path, "valid: 1")
    missing = tmp_path / "missing.yml"
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_files([first, missing])
    assert exc.value.source_path == missing


def test_excessive_nesting_is_a_controlled_error(tmp_path: Path) -> None:
    text = "value: " + "[" * 2000 + "0" + "]" * 2000
    with pytest.raises(YamlLoadError) as exc:
        load_yaml_file(write_yaml(tmp_path, text))
    assert exc.value.code == "excessive_nesting"
