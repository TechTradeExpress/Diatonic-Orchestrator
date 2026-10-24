"""Plain-text presentation of existing offline analyses; no selection algorithms."""

from diatonic.compiler.capabilities import PhaseAnalysis
from diatonic.compiler.graph import DependencyEdge, DependencyGraph
from diatonic.compiler.provider_resolution import (
    CandidateEvaluation,
    ProviderResolution,
    ProviderResolutionError,
)
from diatonic.compiler.references import FieldPath
from diatonic.compiler.stages import StageOrderAnalysis
from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import Lifecycle, Phases


def field_text(path: FieldPath) -> str:
    result = ""
    for segment in path:
        if isinstance(segment, int):
            result += f"[{segment}]"
        else:
            result += ("." if result else "") + segment
    return result


def _edges(title: str, edges: tuple[DependencyEdge, ...]) -> list[str]:
    lines = [f"{title} ({len(edges)}):"]
    if not edges:
        lines.append("  (none)")
    for edge in edges:
        lines.append(f"  {edge.prerequisite_identity} -> {edge.dependent_identity}")
        lines.extend(
            f"    {reason.classification}: owner={reason.resource_identity} "
            f"field={field_text(reason.field_path)}"
            for reason in edge.reasons
        )
    return lines


def _declared(model: ResourceBase | Lifecycle | Phases | None, name: str) -> str:
    if model is None or name not in model.model_fields_set:
        return "(omitted)"
    value = getattr(model, name)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (Lifecycle, Phases)):
        return "declared"
    return str(value)


def candidate_lines(candidates: tuple[CandidateEvaluation, ...]) -> list[str]:
    lines = [f"Candidates ({len(candidates)}):"]
    if not candidates:
        lines.append("  (none)")
    for candidate in candidates:
        lines.extend(
            [
                f"  {candidate.binding_identity}: {candidate.outcome}",
                f"    provider={candidate.provider_identity}; "
                f"priority={candidate.priority}; "
                f"capability={candidate.capability}",
                f"    driver={candidate.driver_id or '(not inspected)'}; "
                f"support={candidate.support_status or '(not inspected)'}",
            ]
        )
        for reason in candidate.reasons:
            line = f"    {reason.code}: field={field_text(reason.field_path)}"
            if reason.expected is not None:
                line += f"; expected={reason.expected!r}"
            if reason.actual is not None:
                line += f"; actual={reason.actual!r}"
            lines.append(line)
    return lines


def resolution_error_text(error: ProviderResolutionError) -> str:
    diagnostic = error.diagnostic
    lines = [f"{diagnostic.code}: {diagnostic.message}"]
    if diagnostic.phase is not None:
        phase = diagnostic.phase
        lines.append(
            f"resource={phase.request.resource_identity}; phase={phase.request.phase}; "
            f"capability={phase.required_capability}"
        )
    lines.extend(
        ["", *candidate_lines(diagnostic.candidates), "", "Sources (document roots):"]
    )
    for identity, source in diagnostic.sources.items():
        location = f"{source.source_path} (document {source.document_index}"
        if source.line is not None:
            location += f", root line {source.line}"
        if source.column is not None:
            location += f", column {source.column}"
        lines.append(f"  resource={identity}; {location})")
    if not diagnostic.sources:
        lines.append("  (none)")
    return "\n".join(lines)


def explanation_text(
    resource: ResourceBase,
    graph: DependencyGraph,
    stages: StageOrderAnalysis,
    analysis: PhaseAnalysis | None,
    resolution: ProviderResolution | None,
) -> str:
    identity = resource.identity
    prerequisites = tuple(e for e in graph.edges if e.dependent_identity == identity)
    dependents = tuple(e for e in graph.edges if e.prerequisite_identity == identity)
    assignment = stages.assignments.get(identity)
    lines = [
        "Resource explanation (offline, not an execution plan)",
        f"Resource: {identity}",
        "",
        *_edges("Direct prerequisites", prerequisites),
        "",
        *_edges("Direct dependents", dependents),
        "",
        "Stage and logical order:",
        (
            f"  Stage: {assignment.stage_identity} (order={assignment.order})"
            if assignment is not None
            else "  Stage: unassigned"
        ),
        f"  Logical topological position: {stages.order.index(identity) + 1} "
        f"of {len(stages.order)}",
        "",
        "Declared lifecycle:",
        f"  lifecycle: {_declared(resource, 'lifecycle')}",
    ]
    lifecycle = resource.lifecycle
    for name in ("stage", "desired_state", "prevent_destroy", "phases"):
        lines.append(f"  lifecycle.{name}: {_declared(lifecycle, name)}")
    phases = lifecycle.phases if lifecycle is not None else None
    for name in ("observe", "provision", "configure"):
        lines.append(f"  lifecycle.phases.{name}: {_declared(phases, name)}")
    if analysis is None:
        lines.extend(["", "Provider resolution: not requested"])
        return "\n".join(lines)
    fact = analysis.fact
    lines.extend(
        [
            "",
            "Offline phase analysis:",
            f"  Requested phase: {fact.request.phase}",
            f"  Ownership: {fact.ownership}",
            f"  Declaration origin: {fact.ownership_origin}",
            f"  Required capability: {fact.required_capability or '(none)'}",
        ]
    )
    assert resolution is not None  # The command completes resolution before formatting.
    if resolution.fact.selection is None:
        description = {
            "external": "externally owned",
            "disabled": "not applicable",
            "unspecified": "unspecified ownership",
        }[resolution.fact.status]
        lines.extend(
            ["", f"Provider resolution: {description}; no managed demand or selection"]
        )
    else:
        selection = resolution.fact.selection
        lines.extend(
            [
                "",
                "Provider resolution: selected (offline declared support only)",
                f"  ProviderBinding: {selection.binding_identity}",
                f"  Provider: {selection.provider_identity}",
                f"  Driver: {selection.driver_id}",
                f"  Priority: {selection.priority}",
                "",
                *candidate_lines(resolution.fact.candidates),
            ]
        )
    return "\n".join(lines)
