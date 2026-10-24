"""Thin CLI for resource compilation and declaration validation."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from diatonic import __version__
from diatonic.compiler.loader import YamlLoadError, load_yaml_files
from diatonic.compiler.normalize import NormalizationError, normalize_resources
from diatonic.compiler.references import (
    FieldPath,
    ResourceResolutionError,
    SourceLocation,
    resolve_resources,
)

app = typer.Typer(
    name="diatonic",
    help="Diatonic Orchestrator: provider-agnostic IaC orchestration.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback(invoke_without_command=True)
def main(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show Diatonic Orchestrator version and exit.",
        is_eager=True,
    ),
) -> None:
    """Diatonic Orchestrator resource compiler."""
    if version:
        Console().print(f"Diatonic Orchestrator {__version__}")
        raise typer.Exit()


def _source_text(source: SourceLocation) -> str:
    location = f"{source.source_path} (document {source.document_index}"
    if source.line is not None:
        location += f", root line {source.line}"
    if source.column is not None:
        location += f", column {source.column}"
    return location + ")"


def _field_text(path: FieldPath) -> str:
    result = ""
    for segment in path:
        if isinstance(segment, int):
            result += f"[{segment}]"
        else:
            result += ("." if result else "") + segment
    return result


def _error_text(
    error: YamlLoadError | ResourceResolutionError | NormalizationError,
) -> str:
    if isinstance(error, YamlLoadError):
        # YAML parser errors may carry precise problem marks; keep them as supplied.
        return str(error)
    if isinstance(error, NormalizationError):
        return (
            f"{_source_text(error.source)}: {error.code}: index key "
            f"{error.indexed_identity!r} differs from resource "
            f"{error.resource_identity!r}"
        )
    diagnostic = error.diagnostic
    details = [f"{_source_text(diagnostic.source)}: {diagnostic.code}"]
    if diagnostic.resource_identity is not None:
        details.append(f"resource={diagnostic.resource_identity}")
    if diagnostic.field_path:
        details.append(f"field={_field_text(diagnostic.field_path)}")
    if diagnostic.reference is not None:
        details.append(f"target={diagnostic.reference}")
    if diagnostic.schema_error_code is not None:
        details.append(f"schema={diagnostic.schema_error_code}")
    details.append(diagnostic.message)
    if diagnostic.related_source is not None:
        details.append(f"first declaration: {_source_text(diagnostic.related_source)}")
    return "; ".join(details)


@app.command()
def validate(
    files: Annotated[
        list[Path],
        typer.Argument(
            help="Explicit YAML files, in supplied order.", metavar="FILE [FILE ...]"
        ),
    ],
) -> None:
    """Check YAML syntax, resource schemas, identities and declared references.

    No directory discovery, cycle checks, provider validation or execution.
    """
    try:
        documents = load_yaml_files(files)
        index = resolve_resources(documents)
        ir = normalize_resources(index)
    except (YamlLoadError, ResourceResolutionError, NormalizationError) as error:
        Console(stderr=True).print(Text(_error_text(error)), soft_wrap=True)
        raise typer.Exit(code=1) from None
    resources, references = len(ir.resources), len(ir.references)
    Console().print(
        f"Validated {resources} resource{'s' if resources != 1 else ''}; "
        f"resolved {references} declared reference{'s' if references != 1 else ''}.",
        markup=False,
        highlight=False,
    )
