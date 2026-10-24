"""Validate configuration links to Providers separately from infrastructure edges."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import ValidationError

from diatonic.compiler.references import (
    FieldPath,
    IndexedResource,
    ResourceIndex,
    SourceLocation,
)
from diatonic.model import Provider, ProviderBinding, ProviderBindingSpec


@dataclass(frozen=True, slots=True)
class BindingSource:
    """Detached document-root provenance, not a field-level location."""

    source_path: Path
    document_index: int
    line: int | None
    column: int | None


@dataclass(frozen=True, slots=True)
class BindingDeclaration:
    """One validated declaration, not a matching decision or selected winner."""

    resource_identity: str
    provider_identity: str
    capability: str
    match_kind: str
    match_labels: Mapping[str, str]
    priority: int
    field_path: FieldPath = ("spec", "provider")

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "match_labels", MappingProxyType(dict(self.match_labels))
        )
        object.__setattr__(self, "field_path", tuple(self.field_path))


@dataclass(frozen=True, slots=True)
class ValidatedProviderBindings:
    declarations: tuple[BindingDeclaration, ...]
    sources: Mapping[str, BindingSource]

    def __post_init__(self) -> None:
        object.__setattr__(self, "declarations", tuple(self.declarations))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))


@dataclass(frozen=True, slots=True)
class BindingDiagnostic:
    code: Literal["missing_binding_provider", "invalid_binding_input"]
    message: str
    resource_identity: str | None
    provider_identity: str | None
    source: BindingSource | None
    field_path: FieldPath = ("spec", "provider")


class ProviderBindingValidationError(ValueError):
    def __init__(self, diagnostic: BindingDiagnostic) -> None:
        self.diagnostic = diagnostic
        location = ""
        if diagnostic.source is not None:
            source = diagnostic.source
            location = f"{source.source_path} (document {source.document_index}"
            if source.line is not None:
                location += f", root line {source.line}"
            if source.column is not None:
                location += f", column {source.column}"
            location += "): "
        super().__init__(
            f"{location}{diagnostic.code}; resource={diagnostic.resource_identity}; "
            f"field=spec.provider; target={diagnostic.provider_identity}; "
            f"{diagnostic.message}"
        )


def _invalid(
    message: str,
    owner: str | None = None,
    target: str | None = None,
    source: BindingSource | None = None,
) -> ProviderBindingValidationError:
    return ProviderBindingValidationError(
        BindingDiagnostic("invalid_binding_input", message, owner, target, source)
    )


def _source(
    source: object,
    owner: str,
    target: str | None,
    owner_source: BindingSource | None = None,
) -> BindingSource:
    if not isinstance(source, SourceLocation) or (
        not isinstance(source.source_path, Path)
        or type(source.document_index) is not int
        or source.document_index < 1
        or any(
            value is not None and (type(value) is not int or value < 1)
            for value in (source.line, source.column)
        )
    ):
        raise _invalid(
            "missing or invalid document-root provenance", owner, target, owner_source
        )
    return BindingSource(
        source.source_path, source.document_index, source.line, source.column
    )


def validate_provider_bindings(index: ResourceIndex) -> ValidatedProviderBindings:
    """Fail fast by canonical binding identity; never resolve selectors or drivers.

    Requires a successful, unmodified ResourceIndex. Revalidate only binding specs
    to reject mutable-model corruption using the existing schema, not new rules.
    """
    if not isinstance(index, ResourceIndex):
        raise TypeError("validate_provider_bindings requires a ResourceIndex")
    if any(not isinstance(key, str) for key in index.resources):
        raise _invalid("resource identity keys must be strings")
    declarations: list[BindingDeclaration] = []
    sources: dict[str, BindingSource] = {}
    for identity in sorted(index.resources):
        entry = index.resources[identity]
        if not isinstance(entry, IndexedResource):
            if identity.startswith("ProviderBinding/"):
                raise _invalid("missing indexed binding record", identity)
            continue
        resource = entry.resource
        if not isinstance(resource, ProviderBinding) and not identity.startswith(
            "ProviderBinding/"
        ):
            continue
        target_hint = (
            resource.spec.provider
            if isinstance(resource, ProviderBinding)
            and isinstance(resource.spec, ProviderBindingSpec)
            and isinstance(resource.spec.provider, str)
            else None
        )
        source = _source(entry.source, identity, target_hint)
        if (
            not isinstance(resource, ProviderBinding)
            or getattr(resource, "identity", None) != identity
        ):
            raise _invalid(
                "binding type or indexed identity mismatch",
                identity,
                target_hint,
                source,
            )
        if not isinstance(resource.spec, ProviderBindingSpec):
            raise _invalid(
                "expected a validated ProviderBindingSpec", identity, source=source
            )
        try:
            spec = ProviderBindingSpec.model_validate(
                resource.spec.model_dump(warnings=False)
            )
        except ValidationError:
            raise _invalid(
                "binding spec no longer satisfies its schema; resolve again",
                identity,
                source=source,
            ) from None
        target = spec.provider
        target_entry = index.resources.get(target)
        if target_entry is None:
            if target in index.resources:
                raise _invalid(
                    "missing indexed Provider record", identity, target, source
                )
            raise ProviderBindingValidationError(
                BindingDiagnostic(
                    "missing_binding_provider",
                    "undeclared Provider target",
                    identity,
                    target,
                    source,
                )
            )
        if (
            not isinstance(target_entry, IndexedResource)
            or not isinstance(target_entry.resource, Provider)
            or getattr(target_entry.resource, "identity", None) != target
        ):
            raise _invalid(
                "target is not a typed Provider with the indexed identity",
                identity,
                target,
                source,
            )
        target_source = _source(target_entry.source, identity, target, source)
        sources[identity] = source
        sources[target] = target_source
        declarations.append(
            BindingDeclaration(
                identity,
                target,
                spec.capability,
                spec.match.kind,
                dict(sorted(spec.match.labels.items())),
                spec.priority,
            )
        )
    return ValidatedProviderBindings(tuple(declarations), dict(sorted(sources.items())))
