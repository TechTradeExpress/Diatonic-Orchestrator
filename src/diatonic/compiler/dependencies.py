"""Classify resolved links as dependency facts or separate Stage assignments."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from diatonic.compiler.references import FieldPath, ResolvedReference, ResourceIndex


@dataclass(frozen=True, slots=True)
class DependencySource:
    """Detached document-root provenance, outside portable relationship facts."""

    source_path: Path
    document_index: int
    line: int | None
    column: int | None


@dataclass(frozen=True, slots=True)
class DependencyFact:
    """One original reference, directed prerequisite → dependent; not an edge."""

    prerequisite_identity: str
    dependent_identity: str
    classification: Literal["explicit", "implicit"]
    resource_identity: str
    field_path: FieldPath


@dataclass(frozen=True, slots=True)
class StageAssignment:
    """A lifecycle Stage link without dependency or Stage-rank semantics."""

    resource_identity: str
    stage_identity: str
    field_path: FieldPath


@dataclass(frozen=True, slots=True)
class DependencyFacts:
    """Portable immutable facts with a separate owner-to-root-source mapping."""

    dependencies: tuple[DependencyFact, ...]
    stage_assignments: tuple[StageAssignment, ...]
    sources: Mapping[str, DependencySource]

    def __post_init__(self) -> None:
        object.__setattr__(self, "dependencies", tuple(self.dependencies))
        object.__setattr__(self, "stage_assignments", tuple(self.stage_assignments))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))


class DependencyClassificationError(ValueError):
    """An unknown reference shape requires a reviewed classification rule."""

    code = "unsupported_reference_field"

    def __init__(self, reference: ResolvedReference) -> None:
        self.resource_identity = reference.resource_identity
        self.target_identity = reference.target_identity
        self.field_path = reference.field_path
        source = reference.source
        self.source = DependencySource(
            source.source_path,
            source.document_index,
            source.line,
            source.column,
        )
        super().__init__(
            f"{source}: {self.code}: resource={self.resource_identity}; "
            f"field={self.field_path!r}; target={self.target_identity}; "
            "expected depends_on[index], lifecycle.stage or a supported VM reference "
            "with nonnegative integer list indexes (coordinates are document root)"
        )


def _reference_order(reference: ResolvedReference) -> tuple[str, int, int]:
    path = reference.field_path
    if not isinstance(path, tuple) or any(
        type(segment) not in (str, int) or (type(segment) is int and segment < 0)
        for segment in path
    ):
        raise DependencyClassificationError(reference)
    owner = reference.resource_identity
    if len(path) == 2 and path[0] == "depends_on" and type(path[1]) is int:
        return owner, 0, path[1]
    if path == ("lifecycle", "stage"):
        return owner, 1, 0
    # Spec rules are intentionally VM-specific, without inspecting mutable models.
    if owner.partition("/")[0] == "VirtualMachine":
        if path == ("spec", "placement", "target"):
            return owner, 2, 0
        if (
            len(path) == 4
            and path[:2] == ("spec", "interfaces")
            and type(path[2]) is int
            and path[3] == "network"
        ):
            return owner, 3, path[2]
        if path == ("spec", "image", "ref"):
            return owner, 4, 0
    raise DependencyClassificationError(reference)


def classify_dependencies(index: ResourceIndex) -> DependencyFacts:
    """Classify each existing resolved link, without lookup or graph analysis.

    Owners sort lexicographically; categories and numeric indexes preserve M1.5's
    declared order. Each reference remains one fact; filenames are never sort keys.
    """
    if not isinstance(index, ResourceIndex):
        raise TypeError("classify_dependencies requires a ResourceIndex")
    ordered = []
    for reference in sorted(index.references, key=lambda ref: ref.resource_identity):
        ordered.append((_reference_order(reference), reference))

    dependencies: list[DependencyFact] = []
    assignments: list[StageAssignment] = []
    sources: dict[str, DependencySource] = {}
    for (_, category, _), reference in sorted(ordered, key=lambda item: item[0]):
        owner = reference.resource_identity
        source = reference.source
        sources[owner] = DependencySource(
            source.source_path,
            source.document_index,
            source.line,
            source.column,
        )
        path = tuple(reference.field_path)
        if category == 1:
            assignments.append(StageAssignment(owner, reference.target_identity, path))
        else:
            dependencies.append(
                DependencyFact(
                    prerequisite_identity=reference.target_identity,
                    dependent_identity=owner,
                    classification="explicit" if category == 0 else "implicit",
                    resource_identity=owner,
                    field_path=path,
                )
            )
    return DependencyFacts(tuple(dependencies), tuple(assignments), sources)
