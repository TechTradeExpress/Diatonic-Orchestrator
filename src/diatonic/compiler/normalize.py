"""Immutable, portable snapshots of a successful resource resolution result."""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from pydantic import JsonValue

from diatonic.compiler.references import FieldPath, ResourceIndex, SourceLocation


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


class NormalizationError(ValueError):
    """An indexed model's mutable identity no longer agrees with its key."""

    code = "identity_mismatch"

    def __init__(
        self, indexed_identity: str, resource_identity: str, source: SourceLocation
    ) -> None:
        self.indexed_identity = indexed_identity
        self.resource_identity = resource_identity
        self.source = source
        super().__init__(
            f"{source}: {self.code}: index key {indexed_identity!r} "
            f"does not match resource identity {resource_identity!r}"
        )


@dataclass(frozen=True, slots=True)
class NormalizedResource:
    """Detached resource data stored as immutable canonical JSON text."""

    identity: str
    _data_json: str

    def to_dict(self) -> dict[str, JsonValue]:
        """Return a fresh decoded resource mapping, with no IR-owned containers."""
        return json.loads(self._data_json)

    def to_json(self) -> str:
        """Return the canonical JSON resource document (without provenance)."""
        return self._data_json


@dataclass(frozen=True, slots=True)
class NormalizedReference:
    """A portable declared link, without execution or source-location semantics."""

    resource_identity: str
    field_path: FieldPath
    target_identity: str

    def to_dict(self) -> dict[str, JsonValue]:
        return {
            "field_path": list(self.field_path),
            "resource_identity": self.resource_identity,
            "target_identity": self.target_identity,
        }


@dataclass(frozen=True, slots=True)
class NormalizedSource:
    """Detached document-root provenance; excluded from portable exports."""

    source_path: Path
    document_index: int
    line: int | None
    column: int | None


@dataclass(frozen=True, slots=True)
class NormalizedIR:
    """Canonical resource/link snapshots with a separate document-root source map."""

    resources: Mapping[str, NormalizedResource]
    references: tuple[NormalizedReference, ...]
    sources: Mapping[str, NormalizedSource]

    def __post_init__(self) -> None:
        # Own the mapping containers, including when constructed directly.
        object.__setattr__(self, "resources", MappingProxyType(dict(self.resources)))
        object.__setattr__(self, "references", tuple(self.references))
        object.__setattr__(self, "sources", MappingProxyType(dict(self.sources)))

    def to_dict(self) -> dict[str, JsonValue]:
        """Export fresh JSON-compatible portable data; source paths are excluded."""
        return {
            "references": [reference.to_dict() for reference in self.references],
            "resources": {
                identity: resource.to_dict()
                for identity, resource in self.resources.items()
            },
        }

    def to_json(self) -> str:
        """Export deterministic JSON text, sorting mapping keys at every depth."""
        return _canonical_json(self.to_dict())


def normalize_resources(index: ResourceIndex) -> NormalizedIR:
    """Snapshot a resolved index, preserving omission/null distinctions and lists.

    Identity keys are checked before serialization. Schema validation and link
    resolution remain M1.5 responsibilities; no index is rebuilt here.
    """
    if not isinstance(index, ResourceIndex):
        raise TypeError("normalize_resources requires a ResourceIndex")
    identities = sorted(index.resources)
    for identity in identities:
        entry = index.resources[identity]
        if identity != entry.resource.identity:
            raise NormalizationError(identity, entry.resource.identity, entry.source)

    resources: dict[str, NormalizedResource] = {}
    sources: dict[str, NormalizedSource] = {}
    for identity in identities:
        entry = index.resources[identity]
        resources[identity] = NormalizedResource(
            identity,
            _canonical_json(
                entry.resource.model_dump(
                    mode="json", exclude_unset=True, warnings="error"
                )
            ),
        )
        sources[identity] = NormalizedSource(
            entry.source.source_path,
            entry.source.document_index,
            entry.source.line,
            entry.source.column,
        )
    # Stable owner sort keeps M1.5's field order and numeric list-index order.
    references = tuple(
        NormalizedReference(
            ref.resource_identity, tuple(ref.field_path), ref.target_identity
        )
        for ref in sorted(index.references, key=lambda ref: ref.resource_identity)
    )
    return NormalizedIR(resources, references, sources)
