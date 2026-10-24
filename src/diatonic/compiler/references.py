"""Validate declarations, index identities and resolve declared resource links."""

from collections.abc import Iterable, Iterator, Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from diatonic.compiler.loader import LoadedDocument
from diatonic.model import Resource, ResourceReference, VirtualMachine, parse_resource

FieldPath = tuple[str | int, ...]
_reference_adapter = TypeAdapter(ResourceReference)


@dataclass(frozen=True)
class SourceLocation:
    """Document-root provenance, never a claim about a field's exact position."""

    source_path: Path
    document_index: int
    line: int | None
    column: int | None

    def __str__(self) -> str:
        position = f":{self.line}:{self.column}" if self.line is not None else ""
        return f"{self.source_path}{position} (document {self.document_index})"


@dataclass(frozen=True)
class ResourceDiagnostic:
    """One deterministic validation failure, with optional schema detail."""

    code: Literal["invalid_resource", "duplicate_identity", "missing_reference"]
    message: str
    source: SourceLocation
    resource_identity: str | None = None
    field_path: FieldPath = ()
    reference: str | None = None
    related_source: SourceLocation | None = None
    schema_error_code: str | None = None


class ResourceResolutionError(ValueError):
    """Fail-fast schema/index/reference error; no partial result is exposed."""

    def __init__(self, diagnostic: ResourceDiagnostic) -> None:
        self.diagnostic = diagnostic
        owner = (
            f" {diagnostic.resource_identity}" if diagnostic.resource_identity else ""
        )
        field = f" at {diagnostic.field_path}" if diagnostic.field_path else ""
        related = (
            f"; first declaration: {diagnostic.related_source}"
            if diagnostic.related_source
            else ""
        )
        super().__init__(
            f"{diagnostic.source}: {diagnostic.code}{owner}{field}: "
            f"{diagnostic.message}{related}"
        )


@dataclass(frozen=True)
class IndexedResource:
    """A validated resource and separate source provenance."""

    resource: Resource
    source: SourceLocation


@dataclass(frozen=True)
class ResolvedReference:
    """A declared link; target_identity is a key in ResourceIndex.resources."""

    resource_identity: str
    field_path: FieldPath
    target_identity: str
    source: SourceLocation


@dataclass(frozen=True)
class ResourceIndex:
    """Read-only mapping in declaration order and links in documented field order.

    Contained Pydantic resources remain mutable; consumers must treat this result
    as a snapshot. It is not normalized IR or an execution dependency graph.
    """

    resources: Mapping[str, IndexedResource]
    references: tuple[ResolvedReference, ...]


def _identity_if_available(data: dict[str, object]) -> str | None:
    kind, metadata = data.get("kind"), data.get("metadata")
    if not isinstance(kind, str) or not isinstance(metadata, dict):
        return None
    name = metadata.get("name")
    if not isinstance(name, str):
        return None
    try:
        return _reference_adapter.validate_python(f"{kind}/{name}", strict=True)
    except ValidationError:
        return None


def _declared_references(resource: Resource) -> Iterator[tuple[FieldPath, str]]:
    for i, reference in enumerate(resource.depends_on):
        yield ("depends_on", i), reference
    if resource.lifecycle is not None and resource.lifecycle.stage is not None:
        yield ("lifecycle", "stage"), f"Stage/{resource.lifecycle.stage}"
    if isinstance(resource, VirtualMachine):
        if resource.spec.placement is not None:
            yield ("spec", "placement", "target"), resource.spec.placement.target
        for i, interface in enumerate(resource.spec.interfaces):
            yield ("spec", "interfaces", i, "network"), interface.network
        if resource.spec.image is not None:
            yield ("spec", "image", "ref"), resource.spec.image.ref


def resolve_resources(documents: Iterable[LoadedDocument]) -> ResourceIndex:
    """Validate/index all documents, then resolve links against the complete index.

    Fail at the first invalid/duplicate declaration in input order. Only after
    indexing succeeds, fail at the first missing link in declaration/field order.
    Schema diagnostics retain the first Pydantic error's path, code and message.
    """
    indexed: dict[str, IndexedResource] = {}
    for document in documents:
        source = SourceLocation(
            document.source_path,
            document.document_index,
            document.line,
            document.column,
        )
        try:
            # Also detach nested extension containers from the caller's data.
            resource = parse_resource(deepcopy(document.data))
        except ValidationError as exc:
            detail = exc.errors(include_url=False, include_input=False)[0]
            path = tuple(detail["loc"])
            # Pydantic union locations include a synthetic discriminator prefix.
            if path and path[0] == document.data.get("kind"):
                path = path[1:]
            if detail["type"] in {"union_tag_invalid", "union_tag_not_found"}:
                path = ("kind",)
            raise ResourceResolutionError(
                ResourceDiagnostic(
                    code="invalid_resource",
                    message=detail["msg"],
                    source=source,
                    resource_identity=_identity_if_available(document.data),
                    field_path=path,
                    schema_error_code=detail["type"],
                )
            ) from exc
        identity = resource.identity
        if identity in indexed:
            raise ResourceResolutionError(
                ResourceDiagnostic(
                    code="duplicate_identity",
                    message=f"duplicate declaration of {identity}",
                    source=source,
                    resource_identity=identity,
                    field_path=("metadata", "name"),
                    related_source=indexed[identity].source,
                )
            )
        indexed[identity] = IndexedResource(resource=resource, source=source)

    references: list[ResolvedReference] = []
    for identity, entry in indexed.items():
        for field_path, target in _declared_references(entry.resource):
            # Typed reference kinds were already checked by the existing schemas.
            # Exact canonical lookup never substitutes a same-named other kind.
            if target not in indexed:
                raise ResourceResolutionError(
                    ResourceDiagnostic(
                        code="missing_reference",
                        message=f"undeclared target {target}",
                        source=entry.source,
                        resource_identity=identity,
                        field_path=field_path,
                        reference=target,
                    )
                )
            references.append(
                ResolvedReference(
                    resource_identity=identity,
                    field_path=field_path,
                    target_identity=target,
                    source=entry.source,
                )
            )
    return ResourceIndex(MappingProxyType(indexed), tuple(references))
