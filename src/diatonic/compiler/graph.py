"""Immutable logical dependency graphs with deterministic directed cycle witnesses."""

from collections import Counter
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from diatonic.compiler.dependencies import (
    DependencyFact,
    DependencyFacts,
    DependencySource,
    StageAssignment,
)
from diatonic.compiler.references import (
    FieldPath,
    IndexedResource,
    ResourceIndex,
    SourceLocation,
)


class DependencyGraphInputError(ValueError):
    """The supplied index and facts cannot describe one consistent analysis."""

    code = "invalid_graph_input"

    def __init__(self, reason: str, resource_identity: str | None = None) -> None:
        self.reason = reason
        self.resource_identity = resource_identity
        owner = (
            f" resource={resource_identity};" if resource_identity is not None else ""
        )
        super().__init__(f"{self.code}:{owner} {reason}")


def _source(source: object, owner: str) -> DependencySource:
    if not isinstance(source, (SourceLocation, DependencySource)):
        raise DependencyGraphInputError(
            "missing required document-root provenance", owner
        )
    if (
        not isinstance(source.source_path, Path)
        or type(source.document_index) is not int
        or source.document_index < 1
        or any(
            value is not None and (type(value) is not int or value < 1)
            for value in (source.line, source.column)
        )
    ):
        raise DependencyGraphInputError("invalid document-root provenance", owner)
    return DependencySource(
        source.source_path, source.document_index, source.line, source.column
    )


def _path(path: FieldPath, owner: str) -> FieldPath:
    if (
        not isinstance(path, tuple)
        or not path
        or any(
            type(segment) not in (str, int) or (type(segment) is int and segment < 0)
            for segment in path
        )
    ):
        raise DependencyGraphInputError(f"invalid fact field path {path!r}", owner)
    return tuple(path)


def _reason_key(fact: DependencyFact) -> tuple:
    groups = {
        ("depends_on",): 0,
        ("spec", "placement"): 1,
        ("spec", "interfaces"): 2,
        ("spec", "image"): 3,
    }
    group = groups.get(fact.field_path[:2], groups.get(fact.field_path[:1], 4))
    path = tuple(
        (0, part) if isinstance(part, str) else (1, part) for part in fact.field_path
    )
    return (
        0 if fact.classification == "explicit" else 1,
        fact.resource_identity,
        group,
        path,
    )


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    prerequisite_identity: str
    dependent_identity: str
    reasons: tuple[DependencyFact, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True, slots=True)
class DependencyGraph:
    """Cycle-checked logical facts; no phase, Stage-order or execution semantics."""

    vertices: tuple[str, ...]
    edges: tuple[DependencyEdge, ...]
    successors: Mapping[str, tuple[str, ...]]
    sources: Mapping[str, DependencySource]
    stage_assignments: tuple[StageAssignment, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "vertices", tuple(self.vertices))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(
            self,
            "successors",
            MappingProxyType(
                {key: tuple(value) for key, value in self.successors.items()}
            ),
        )
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))
        object.__setattr__(self, "stage_assignments", tuple(self.stage_assignments))


@dataclass(frozen=True, slots=True)
class DependencyCycleDiagnostic:
    witness: tuple[str, ...]
    edges: tuple[DependencyEdge, ...]
    sources: Mapping[str, DependencySource]

    def __post_init__(self) -> None:
        object.__setattr__(self, "witness", tuple(self.witness))
        object.__setattr__(self, "edges", tuple(self.edges))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))


class DependencyCycleError(ValueError):
    code = "dependency_cycle"

    def __init__(self, diagnostic: DependencyCycleDiagnostic) -> None:
        self.diagnostic = diagnostic
        details = []
        for edge in diagnostic.edges:
            for fact in edge.reasons:
                source = diagnostic.sources[fact.resource_identity]
                details.append(
                    f"{edge.prerequisite_identity} -> {edge.dependent_identity}: "
                    f"{fact.classification} owner={fact.resource_identity} "
                    f"field={fact.field_path!r} at {source.source_path} "
                    f"(document {source.document_index}, root line {source.line}, "
                    f"column {source.column})"
                )
        super().__init__(
            f"{self.code}: {' -> '.join(diagnostic.witness)}; " + "; ".join(details)
        )


def _find_cycle(
    vertices: tuple[str, ...],
    successors: Mapping[str, tuple[str, ...]],
) -> tuple[str, ...] | None:
    finished: set[str] = set()
    active: list[str] = []
    positions: dict[str, int] = {}
    stack: list[tuple[str, Iterator[str]]] = []
    for root in vertices:
        if root in finished:
            continue
        active.append(root)
        positions[root] = 0
        stack.append((root, iter(successors[root])))
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                stack.pop()
                active.pop()
                del positions[node]
                finished.add(node)
            elif child in positions:
                cycle = active[positions[child] :]
                pivot = min(range(len(cycle)), key=cycle.__getitem__)
                rotated = cycle[pivot:] + cycle[:pivot]
                return (*rotated, rotated[0])
            elif child not in finished:
                positions[child] = len(active)
                active.append(child)
                stack.append((child, iter(successors[child])))
    return None


def build_dependency_graph(
    index: ResourceIndex, facts: DependencyFacts
) -> DependencyGraph:
    """Build atomically from matching successful resolver/classification results."""
    if not isinstance(index, ResourceIndex) or not isinstance(facts, DependencyFacts):
        raise TypeError(
            "build_dependency_graph requires ResourceIndex and DependencyFacts"
        )
    if any(not isinstance(identity, str) for identity in index.resources):
        raise DependencyGraphInputError("resource identity keys must be strings")
    vertices = tuple(sorted(index.resources))
    sources: dict[str, DependencySource] = {}
    for identity in vertices:
        entry = index.resources[identity]
        if not isinstance(entry, IndexedResource):
            raise DependencyGraphInputError(
                "missing indexed resource/provenance record", identity
            )
        if getattr(entry.resource, "identity", None) != identity:
            raise DependencyGraphInputError(
                "index key disagrees with resource identity", identity
            )
        sources[identity] = _source(entry.source, identity)

    for owner, source in facts.sources.items():
        if owner not in sources:
            raise DependencyGraphInputError("unknown fact source owner", owner)
        if _source(source, owner) != sources[owner]:
            raise DependencyGraphInputError("fact/index provenance mismatch", owner)

    actual: Counter = Counter()
    grouped: dict[tuple[str, str], list[DependencyFact]] = {}
    for fact in facts.dependencies:
        owner, prerequisite, dependent = (
            fact.resource_identity,
            fact.prerequisite_identity,
            fact.dependent_identity,
        )
        for role, identity in (
            ("prerequisite", prerequisite),
            ("dependent", dependent),
            ("owner", owner),
        ):
            if identity not in sources:
                raise DependencyGraphInputError(
                    f"unknown {role} identity {identity!r}", owner
                )
        if owner != dependent:
            raise DependencyGraphInputError("fact owner must equal dependent", owner)
        if owner not in facts.sources:
            raise DependencyGraphInputError("missing fact owner provenance", owner)
        path = _path(fact.field_path, owner)
        explicit = len(path) == 2 and path[0] == "depends_on" and type(path[1]) is int
        if (
            fact.classification not in ("explicit", "implicit")
            or (fact.classification == "explicit") != explicit
            or path == ("lifecycle", "stage")
        ):
            raise DependencyGraphInputError(
                "incompatible dependency classification", owner
            )
        actual[owner, path, prerequisite] += 1
        grouped.setdefault((prerequisite, dependent), []).append(
            DependencyFact(
                prerequisite,
                dependent,
                fact.classification,
                owner,
                path,
            )
        )

    assignments = []
    for assignment in facts.stage_assignments:
        owner, target = assignment.resource_identity, assignment.stage_identity
        if (
            owner not in sources
            or target not in sources
            or not target.startswith("Stage/")
        ):
            raise DependencyGraphInputError(
                "unknown owner or incompatible Stage target", owner
            )
        if owner not in facts.sources:
            raise DependencyGraphInputError(
                "missing Stage-assignment owner provenance", owner
            )
        path = _path(assignment.field_path, owner)
        if path != ("lifecycle", "stage"):
            raise DependencyGraphInputError(
                "incompatible Stage-assignment field", owner
            )
        actual[owner, path, target] += 1
        assignments.append(StageAssignment(owner, target, path))

    expected: Counter = Counter()
    for reference in index.references:
        owner, target = reference.resource_identity, reference.target_identity
        if owner not in sources or target not in sources:
            raise DependencyGraphInputError(
                "resolved reference has unknown endpoints", owner
            )
        if _source(reference.source, owner) != sources[owner]:
            raise DependencyGraphInputError(
                "reference/index provenance mismatch", owner
            )
        expected[owner, _path(reference.field_path, owner), target] += 1
    if expected != actual:
        raise DependencyGraphInputError(
            f"facts do not match recorded references: "
            f"{sum((expected - actual).values())} missing, "
            f"{sum((actual - expected).values())} extra"
        )

    edges = tuple(
        DependencyEdge(a, b, tuple(sorted(reasons, key=_reason_key)))
        for (a, b), reasons in sorted(grouped.items())
    )
    adjacency: dict[str, list[str]] = {identity: [] for identity in vertices}
    for edge in edges:
        adjacency[edge.prerequisite_identity].append(edge.dependent_identity)
    successors = {identity: tuple(children) for identity, children in adjacency.items()}
    witness = _find_cycle(vertices, successors)
    if witness is not None:
        by_pair = {(e.prerequisite_identity, e.dependent_identity): e for e in edges}
        cycle_edges = tuple(
            by_pair[pair] for pair in zip(witness[:-1], witness[1:], strict=True)
        )
        cycle_sources = {
            identity: sources[identity] for identity in sorted(set(witness))
        }
        raise DependencyCycleError(
            DependencyCycleDiagnostic(witness, cycle_edges, cycle_sources)
        )
    return DependencyGraph(
        vertices,
        edges,
        successors,
        sources,
        tuple(sorted(assignments, key=lambda item: item.resource_identity)),
    )
