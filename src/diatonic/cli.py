"""Thin CLI for resource compilation and declaration validation."""

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.text import Text

from diatonic import __version__
from diatonic.compiler.dependencies import (
    DependencyClassificationError,
    DependencySource,
    classify_dependencies,
)
from diatonic.compiler.graph import (
    DependencyCycleError,
    DependencyEdge,
    DependencyGraph,
    DependencyGraphInputError,
    build_dependency_graph,
)
from diatonic.compiler.loader import YamlLoadError, load_yaml_files
from diatonic.compiler.normalize import NormalizationError, normalize_resources
from diatonic.compiler.references import (
    FieldPath,
    ResourceResolutionError,
    SourceLocation,
    resolve_resources,
)
from diatonic.compiler.semantics import SemanticValidationError, validate_ipv4_semantics
from diatonic.compiler.stages import (
    StageOrderAnalysis,
    StageOrderConflictError,
    StageOrderInputError,
    analyze_stage_order,
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


def _source_text(source: SourceLocation | DependencySource) -> str:
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
    error: YamlLoadError
    | ResourceResolutionError
    | NormalizationError
    | SemanticValidationError,
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
    if isinstance(error, SemanticValidationError):
        semantic = error.diagnostic
        details = [
            f"{_source_text(semantic.source)}: {semantic.code}",
            f"resource={semantic.resource_identity}",
            f"field={_field_text(semantic.field_path)}",
            f"network={semantic.network_identity}",
            f"cidr={semantic.cidr}",
            f"address={semantic.address}",
            semantic.message,
        ]
        if semantic.related is not None:
            related = semantic.related
            details.append(
                f"conflicting declaration: {_source_text(related.source)}; "
                f"resource={related.resource_identity}; "
                f"field={_field_text(related.field_path)}; "
                f"address={related.address}"
            )
        return "; ".join(details)
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
    """Check YAML syntax, schemas, identities, references and declared IPv4 semantics.

    No directory discovery, cycle checks, provider validation or execution.
    """
    try:
        documents = load_yaml_files(files)
        index = resolve_resources(documents)
        validate_ipv4_semantics(index)
        ir = normalize_resources(index)
    except (
        YamlLoadError,
        ResourceResolutionError,
        NormalizationError,
        SemanticValidationError,
    ) as error:
        Console(stderr=True).print(Text(_error_text(error)), soft_wrap=True)
        raise typer.Exit(code=1) from None
    resources, references = len(ir.resources), len(ir.references)
    Console().print(
        f"Validated {resources} resource{'s' if resources != 1 else ''}; "
        f"resolved {references} declared reference{'s' if references != 1 else ''}.",
        markup=False,
        highlight=False,
    )


def _dependency_lines(edges: tuple[DependencyEdge, ...]) -> list[str]:
    lines = [f"Dependencies ({len(edges)}):"]
    if not edges:
        lines.append("  (none)")
    for edge in edges:
        lines.append(f"  {edge.prerequisite_identity} -> {edge.dependent_identity}")
        lines.extend(
            f"    {reason.classification}: owner={reason.resource_identity} "
            f"field={_field_text(reason.field_path)}"
            for reason in edge.reasons
        )
    return lines


def _graph_text(graph: DependencyGraph, analysis: StageOrderAnalysis) -> str:
    vertices, edges = len(graph.vertices), len(graph.edges)
    assignments = len(analysis.assignments)
    reasons = sum(len(edge.reasons) for edge in graph.edges)
    lines = [
        "Logical dependency graph (offline, not an execution plan)",
        f"Resources: {vertices}; dependency edges: {edges}; "
        f"declared reasons: {reasons}; Stage assignments: {assignments}",
        "",
        f"Vertices ({vertices}):",
        *(f"  {identity}" for identity in graph.vertices or ("(none)",)),
        "",
        *_dependency_lines(graph.edges),
        "",
        f"Stage assignments ({assignments}):",
    ]
    lines.extend(
        [
            f"  {assignment.resource_identity} -> {assignment.stage_identity} "
            f"(order={assignment.order})"
            for assignment in analysis.assignments.values()
        ]
        or ["  (none)"]
    )
    lines.extend(["", f"Topological order ({len(analysis.order)}):"])
    lines.extend(
        [f"  {i}. {identity}" for i, identity in enumerate(analysis.order, 1)]
        or ["  (none)"]
    )
    return "\n".join(lines)


def _graph_error_text(
    error: DependencyClassificationError
    | DependencyGraphInputError
    | DependencyCycleError
    | StageOrderInputError
    | StageOrderConflictError,
) -> str:
    if isinstance(error, DependencyClassificationError):
        return (
            f"{_source_text(error.source)}: {error.code}; "
            f"resource={error.resource_identity}; "
            f"field={error.field_path!r}; "
            f"target={error.target_identity}; unsupported reference field"
        )
    if isinstance(error, (DependencyGraphInputError, StageOrderInputError)):
        return str(error)
    diagnostic = error.diagnostic
    prefix = "dependency path " if isinstance(error, StageOrderConflictError) else ""
    lines = [f"{error.code}: {prefix}{' -> '.join(diagnostic.witness)}"]
    if isinstance(error, StageOrderConflictError):
        conflict = error.diagnostic
        lines.extend(["", "Conflicting Stage assignments (2):"])
        lines.extend(
            f"  {assignment.resource_identity} -> {assignment.stage_identity} "
            f"(order={assignment.order}) field={_field_text(assignment.field_path)}"
            for assignment in (conflict.higher, conflict.lower)
        )
    lines.extend(
        ["", *_dependency_lines(diagnostic.edges), "", "Sources (document roots):"]
    )
    lines.extend(
        f"  resource={identity}; {_source_text(source)}"
        for identity, source in diagnostic.sources.items()
    )
    return "\n".join(lines)


@app.command()
def graph(
    files: Annotated[
        list[Path],
        typer.Argument(
            help="Explicit YAML files, in supplied order.", metavar="FILE [FILE ...]"
        ),
    ],
) -> None:
    """Show offline dependencies, Stage assignments and topological order.

    No provider initialization, execution, planning or directory discovery.
    """
    try:
        documents = load_yaml_files(files)
        index = resolve_resources(documents)
        validate_ipv4_semantics(index)
        normalize_resources(index)
        facts = classify_dependencies(index)
        dependency_graph = build_dependency_graph(index, facts)
        analysis = analyze_stage_order(index, dependency_graph)
    except (
        YamlLoadError,
        ResourceResolutionError,
        NormalizationError,
        SemanticValidationError,
    ) as error:
        Console(stderr=True).print(Text(_error_text(error)), soft_wrap=True)
        raise typer.Exit(code=1) from None
    except (
        DependencyClassificationError,
        DependencyGraphInputError,
        DependencyCycleError,
        StageOrderInputError,
        StageOrderConflictError,
    ) as error:
        Console(stderr=True).print(Text(_graph_error_text(error)), soft_wrap=True)
        raise typer.Exit(code=1) from None
    Console().print(Text(_graph_text(dependency_graph, analysis)), soft_wrap=True)
