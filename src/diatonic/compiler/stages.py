"""Offline Stage-group constraints over an already cycle-checked logical graph."""

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from heapq import heapify, heappop, heappush
from pathlib import Path
from types import MappingProxyType

from diatonic.compiler.dependencies import DependencySource
from diatonic.compiler.graph import DependencyEdge, DependencyGraph
from diatonic.compiler.references import (
    FieldPath,
    IndexedResource,
    ResourceIndex,
    SourceLocation,
)
from diatonic.model import Stage
from diatonic.model.lifecycle import Lifecycle
from diatonic.model.stage import StageSpec


class StageOrderInputError(ValueError):
    """The index and graph are not compatible successful compiler results."""

    code = "invalid_stage_order_input"

    def __init__(self, reason: str, resource_identity: str | None = None) -> None:
        self.reason = reason
        self.resource_identity = resource_identity
        super().__init__(f"{self.code}: resource={resource_identity}; {reason}")


@dataclass(frozen=True, slots=True)
class RankedStageAssignment:
    resource_identity: str
    stage_identity: str
    order: int
    field_path: FieldPath


@dataclass(frozen=True, slots=True)
class StageOrderAnalysis:
    """Detached offline ordering and ranks; sources are not portable sort keys."""

    order: tuple[str, ...]
    stage_orders: Mapping[str, int]
    assignments: Mapping[str, RankedStageAssignment]
    sources: Mapping[str, DependencySource]

    def __post_init__(self) -> None:
        object.__setattr__(self, "order", tuple(self.order))
        for name in ("stage_orders", "assignments", "sources"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True, slots=True)
class StageConflictDiagnostic:
    higher: RankedStageAssignment
    lower: RankedStageAssignment
    witness: tuple[str, ...]
    edges: tuple[DependencyEdge, ...]
    sources: Mapping[str, DependencySource]

    def __post_init__(self) -> None:
        object.__setattr__(self, "witness", tuple(self.witness))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))


class StageOrderConflictError(ValueError):
    code = "stage_order_conflict"

    def __init__(self, diagnostic: StageConflictDiagnostic) -> None:
        self.diagnostic = diagnostic
        details = []
        for assignment in (diagnostic.higher, diagnostic.lower):
            details.append(
                f"{assignment.resource_identity} assigned to "
                f"{assignment.stage_identity} "
                f"order={assignment.order} field={assignment.field_path!r}"
            )
        for edge in diagnostic.edges:
            for reason in edge.reasons:
                details.append(
                    f"{edge.prerequisite_identity} -> {edge.dependent_identity}: "
                    f"{reason.classification} owner={reason.resource_identity} "
                    f"field={reason.field_path!r}"
                )
        for identity, source in diagnostic.sources.items():
            details.append(
                f"{identity} at {source.source_path} "
                f"(document {source.document_index}, "
                f"root line {source.line}, column {source.column})"
            )
        super().__init__(
            f"{self.code}: dependency path {' -> '.join(diagnostic.witness)}; "
            + "; ".join(details)
        )


def _source(source: object, owner: str) -> DependencySource:
    if not isinstance(source, (SourceLocation, DependencySource)) or (
        not isinstance(source.source_path, Path)
        or type(source.document_index) is not int
        or source.document_index < 1
        or any(
            value is not None and (type(value) is not int or value < 1)
            for value in (source.line, source.column)
        )
    ):
        raise StageOrderInputError("missing or invalid document-root provenance", owner)
    return DependencySource(
        source.source_path, source.document_index, source.line, source.column
    )


def _link(owner: str, path: FieldPath, target: str) -> tuple[str, FieldPath, str]:
    if (
        not isinstance(path, tuple)
        or not path
        or any(
            type(part) not in (str, int) or (type(part) is int and part < 0)
            for part in path
        )
    ):
        raise StageOrderInputError("invalid recorded field path", owner)
    return owner, path, target


def _inputs(
    index: ResourceIndex, graph: DependencyGraph
) -> tuple[
    dict[str, DependencySource],
    dict[str, int],
    dict[str, RankedStageAssignment],
    dict[tuple[str, str], DependencyEdge],
    dict[str, int],
]:
    """Focused compatibility guards, without schema parsing or reclassification."""
    if any(not isinstance(key, str) for key in index.resources):
        raise StageOrderInputError("identity keys must be strings")
    vertices = tuple(sorted(index.resources))
    if graph.vertices != vertices:
        raise StageOrderInputError("graph/index vertex mismatch")
    if set(graph.sources) != set(vertices) or set(graph.successors) != set(vertices):
        raise StageOrderInputError("graph is missing vertex provenance or adjacency")
    sources: dict[str, DependencySource] = {}
    stage_orders: dict[str, int] = {}
    for identity in vertices:
        entry = index.resources[identity]
        if (
            not isinstance(entry, IndexedResource)
            or getattr(entry.resource, "identity", None) != identity
        ):
            raise StageOrderInputError("indexed resource identity mismatch", identity)
        sources[identity] = _source(entry.source, identity)
        if sources[identity] != _source(graph.sources[identity], identity):
            raise StageOrderInputError("graph/index provenance mismatch", identity)
        if identity.startswith("Stage/"):
            resource = entry.resource
            if (
                not isinstance(resource, Stage)
                or not isinstance(resource.spec, StageSpec)
                or type(resource.spec.order) is not int
            ):
                raise StageOrderInputError(
                    "expected validated Stage with strict integer order", identity
                )
            stage_orders[identity] = resource.spec.order

    assignments: dict[str, RankedStageAssignment] = {}
    links: Counter[tuple[str, FieldPath, str]] = Counter()
    for assignment in graph.stage_assignments:
        owner, target = assignment.resource_identity, assignment.stage_identity
        if owner not in sources or target not in stage_orders:
            raise StageOrderInputError(
                "unknown assignment owner or missing/wrong-kind Stage", owner
            )
        if owner in assignments or assignment.field_path != ("lifecycle", "stage"):
            raise StageOrderInputError("duplicate or invalid Stage assignment", owner)
        assignments[owner] = RankedStageAssignment(
            owner, target, stage_orders[target], tuple(assignment.field_path)
        )
        links[_link(owner, assignment.field_path, target)] += 1
    for identity in vertices:
        lifecycle = index.resources[identity].resource.lifecycle
        if lifecycle is not None and not isinstance(lifecycle, Lifecycle):
            raise StageOrderInputError("expected validated lifecycle", identity)
        target = (
            f"Stage/{lifecycle.stage}"
            if lifecycle is not None and lifecycle.stage is not None
            else None
        )
        recorded = (
            assignments[identity].stage_identity if identity in assignments else None
        )
        if target != recorded:
            raise StageOrderInputError(
                "model/graph Stage assignment mismatch", identity
            )

    by_pair: dict[tuple[str, str], DependencyEdge] = {}
    successors: dict[str, list[str]] = {identity: [] for identity in vertices}
    indegrees = dict.fromkeys(vertices, 0)
    for edge in graph.edges:
        a, b = edge.prerequisite_identity, edge.dependent_identity
        if (
            a not in sources
            or b not in sources
            or (a, b) in by_pair
            or not edge.reasons
        ):
            raise StageOrderInputError(
                "invalid, duplicate or unexplained graph edge", b
            )
        by_pair[a, b] = edge
        successors[a].append(b)
        indegrees[b] += 1
        for reason in edge.reasons:
            if (
                (
                    reason.prerequisite_identity,
                    reason.dependent_identity,
                    reason.resource_identity,
                )
                != (a, b, b)
                or reason.classification not in ("explicit", "implicit")
                or reason.field_path == ("lifecycle", "stage")
            ):
                raise StageOrderInputError("edge reason endpoints/category mismatch", b)
            links[_link(b, reason.field_path, a)] += 1
    if any(tuple(sorted(successors[v])) != graph.successors[v] for v in vertices):
        raise StageOrderInputError("edges/successor adjacency mismatch")
    recorded_links: Counter[tuple[str, FieldPath, str]] = Counter()
    for reference in index.references:
        owner, target = reference.resource_identity, reference.target_identity
        if owner not in sources or target not in sources:
            raise StageOrderInputError(
                "recorded reference has unknown endpoints", owner
            )
        if _source(reference.source, owner) != sources[owner]:
            raise StageOrderInputError("reference/index provenance mismatch", owner)
        recorded_links[_link(owner, reference.field_path, target)] += 1
    if recorded_links != links:
        raise StageOrderInputError(
            "graph reasons/assignments do not match index references"
        )
    return sources, stage_orders, dict(sorted(assignments.items())), by_pair, indegrees


def _dependency_order(
    graph: DependencyGraph, indegrees: dict[str, int]
) -> tuple[str, ...]:
    counts = dict(indegrees)
    ready = [v for v in graph.vertices if not counts[v]]
    heapify(ready)
    ordered = []
    while ready:
        node = heappop(ready)
        ordered.append(node)
        for child in graph.successors[node]:
            counts[child] -= 1
            if not counts[child]:
                heappush(ready, child)
    if len(ordered) != len(graph.vertices):
        raise StageOrderInputError(
            "graph must be cycle-checked by build_dependency_graph first"
        )
    return tuple(ordered)


def _check_conflicts(
    graph: DependencyGraph,
    ordered: tuple[str, ...],
    assignments: Mapping[str, RankedStageAssignment],
    by_pair: Mapping[tuple[str, str], DependencyEdge],
    sources: Mapping[str, DependencySource],
) -> None:
    # One best ranked ancestor and one parent per vertex, not copied path prefixes.
    best: dict[str, str] = {}
    parent: dict[str, str] = {}

    def priority(owner: str) -> tuple[int, str]:
        return -assignments[owner].order, owner

    for node in ordered:
        ancestor = best.get(node)
        own = assignments.get(node)
        if (
            own is not None
            and ancestor is not None
            and assignments[ancestor].order > own.order
        ):
            path = [node]
            while path[-1] != ancestor:
                path.append(parent[path[-1]])
            witness = tuple(reversed(path))
            higher = assignments[ancestor]
            identities = set(witness) | {higher.stage_identity, own.stage_identity}
            raise StageOrderConflictError(
                StageConflictDiagnostic(
                    higher,
                    own,
                    witness,
                    tuple(
                        by_pair[pair]
                        for pair in zip(witness[:-1], witness[1:], strict=True)
                    ),
                    {identity: sources[identity] for identity in sorted(identities)},
                )
            )
        if own is not None and (
            ancestor is None or priority(node) < priority(ancestor)
        ):
            best[node] = node
            parent.pop(node, None)
        if node not in best:
            continue
        for child in graph.successors[node]:
            candidate = best[node]
            if child not in best or priority(candidate) < priority(best[child]):
                best[child] = candidate
                parent[child] = node


def _group_order(
    graph: DependencyGraph,
    assignments: Mapping[str, RankedStageAssignment],
    indegrees: dict[str, int],
) -> tuple[str, ...]:
    counts = dict(indegrees)
    remaining = Counter(assignment.order for assignment in assignments.values())
    groups = sorted(remaining)
    active = 0
    ready: list[str] = []
    waiting: dict[int, list[str]] = {rank: [] for rank in groups}

    def release(node: str) -> None:
        assignment = assignments.get(node)
        if assignment is None or assignment.order == groups[active]:
            heappush(ready, node)
        else:
            waiting[assignment.order].append(node)

    for node in graph.vertices:
        if not counts[node]:
            release(node)
    ordered = []
    while ready:
        node = heappop(ready)
        ordered.append(node)
        assignment = assignments.get(node)
        if assignment is not None:
            remaining[assignment.order] -= 1
            if not remaining[assignment.order]:
                active += 1
                if active < len(groups):
                    for released in waiting[groups[active]]:
                        heappush(ready, released)
                    waiting[groups[active]].clear()
        for child in graph.successors[node]:
            counts[child] -= 1
            if not counts[child]:
                release(child)
    if len(ordered) != len(graph.vertices):
        raise StageOrderInputError(
            "incompatible graph or Stage constraints after conflict analysis"
        )
    return tuple(ordered)


def analyze_stage_order(
    index: ResourceIndex, graph: DependencyGraph
) -> StageOrderAnalysis:
    """Apply strict Stage groups without mutating declared edges or M1 behavior."""
    if not isinstance(index, ResourceIndex) or not isinstance(graph, DependencyGraph):
        raise TypeError(
            "analyze_stage_order requires ResourceIndex and DependencyGraph"
        )
    sources, stage_orders, assignments, by_pair, indegrees = _inputs(index, graph)
    ordered = _dependency_order(graph, indegrees)
    _check_conflicts(graph, ordered, assignments, by_pair, sources)
    result = _group_order(graph, assignments, indegrees)
    return StageOrderAnalysis(result, stage_orders, assignments, sources)
