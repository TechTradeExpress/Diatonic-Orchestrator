"""Explicit offline phase demand and independent supplied driver support facts."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from diatonic.compiler.references import (
    FieldPath,
    IndexedResource,
    ResourceIndex,
    SourceLocation,
)
from diatonic.model import (
    Hypervisor,
    Image,
    Network,
    Provider,
    ProviderBinding,
    Stage,
    VirtualMachine,
)
from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import Lifecycle, Phases
from diatonic.model.types import ResourceName, ResourceReference

Phase = Literal["observe", "provision", "configure"]
OwnershipOutcome = Literal["managed", "external", "disabled", "unspecified"]
SupportStatus = Literal[
    "declared_supported", "declared_unsupported", "metadata_unavailable"
]
OwnershipOrigin = Literal[
    "lifecycle_omitted",
    "lifecycle_null",
    "phases_omitted",
    "phases_null",
    "phase_omitted",
    "phase_null",
    "declared",
]

CAPABILITY_VOCABULARY: Mapping[tuple[str, Phase], str] = MappingProxyType(
    dict(
        sorted(
            {
                ("VirtualMachine", "observe"): "virtual_machine.observe",
                ("VirtualMachine", "provision"): "virtual_machine.provision",
                ("VirtualMachine", "configure"): "virtual_machine.configure",
                ("Network", "observe"): "network.observe",
                ("Network", "provision"): "network.provision",
                ("Hypervisor", "observe"): "hypervisor.observe",
                ("Hypervisor", "configure"): "hypervisor.configure",
            }.items()
        )
    )
)
_RESOURCE_TYPES = {
    "VirtualMachine": VirtualMachine,
    "Network": Network,
    "Hypervisor": Hypervisor,
    "Image": Image,
    "Stage": Stage,
    "Provider": Provider,
    "ProviderBinding": ProviderBinding,
}
_name_adapter = TypeAdapter(ResourceName)
_reference_adapter = TypeAdapter(ResourceReference)
_MISSING = object()


@dataclass(frozen=True, slots=True)
class PhaseSource:
    """Detached document-root provenance, separate from portable phase facts."""

    source_path: Path
    document_index: int
    line: int | None
    column: int | None


@dataclass(frozen=True, slots=True)
class PhaseDiagnostic:
    code: Literal[
        "invalid_phase_request",
        "unknown_phase_resource",
        "unsupported_managed_phase",
        "invalid_phase_input",
    ]
    message: str
    resource_identity: str | None = None
    phase: str | None = None
    source: PhaseSource | None = None
    field_path: FieldPath = ()


class PhaseAnalysisError(ValueError):
    def __init__(self, diagnostic: PhaseDiagnostic) -> None:
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
            f"phase={diagnostic.phase}; field={diagnostic.field_path!r}; "
            f"{diagnostic.message}"
        )


@dataclass(frozen=True, slots=True)
class PhaseRequest:
    resource_identity: str
    phase: Phase

    def __post_init__(self) -> None:
        try:
            identity = _reference_adapter.validate_python(
                self.resource_identity, strict=True
            )
        except ValidationError:
            raise PhaseAnalysisError(
                PhaseDiagnostic(
                    "invalid_phase_request",
                    "resource_identity must use strict canonical Kind/name syntax",
                    field_path=("resource_identity",),
                )
            ) from None
        if type(self.phase) is not str or self.phase not in (
            "observe",
            "provision",
            "configure",
        ):
            raise PhaseAnalysisError(
                PhaseDiagnostic(
                    "invalid_phase_request",
                    "phase must be observe, provision or configure",
                    identity,
                    self.phase if type(self.phase) is str else None,
                    field_path=("phase",),
                )
            )
        object.__setattr__(self, "resource_identity", identity)


@dataclass(frozen=True, slots=True)
class PhaseFact:
    """Portable demand declaration, without source paths or provider decisions."""

    request: PhaseRequest
    ownership: OwnershipOutcome
    ownership_origin: OwnershipOrigin
    required_capability: str | None


@dataclass(frozen=True, slots=True)
class PhaseAnalysis:
    """An immutable portable fact paired with detached root provenance."""

    fact: PhaseFact
    source: PhaseSource


def _invalid_phase_input(
    message: str, request: PhaseRequest, source: PhaseSource | None = None
) -> PhaseAnalysisError:
    return PhaseAnalysisError(
        PhaseDiagnostic(
            "invalid_phase_input",
            message,
            request.resource_identity,
            request.phase,
            source,
            ("lifecycle", "phases", request.phase),
        )
    )


def _source(source: object, request: PhaseRequest) -> PhaseSource:
    if not isinstance(source, SourceLocation) or (
        not isinstance(source.source_path, Path)
        or type(source.document_index) is not int
        or source.document_index < 1
        or any(
            value is not None and (type(value) is not int or value < 1)
            for value in (source.line, source.column)
        )
    ):
        raise _invalid_phase_input(
            "missing or invalid document-root provenance", request
        )
    return PhaseSource(
        source.source_path, source.document_index, source.line, source.column
    )


def _ownership(
    resource: ResourceBase, request: PhaseRequest, source: PhaseSource
) -> tuple[OwnershipOutcome, OwnershipOrigin]:
    lifecycle = getattr(resource, "lifecycle", _MISSING)
    if lifecycle is None:
        return (
            "unspecified",
            "lifecycle_null"
            if "lifecycle" in resource.model_fields_set
            else "lifecycle_omitted",
        )
    if (
        not isinstance(lifecycle, Lifecycle)
        or "lifecycle" not in resource.model_fields_set
    ):
        raise _invalid_phase_input(
            "expected a declared, typed Lifecycle", request, source
        )
    phases = getattr(lifecycle, "phases", _MISSING)
    if phases is None:
        return (
            "unspecified",
            "phases_null"
            if "phases" in lifecycle.model_fields_set
            else "phases_omitted",
        )
    if not isinstance(phases, Phases) or "phases" not in lifecycle.model_fields_set:
        raise _invalid_phase_input(
            "expected a declared, typed Phases object", request, source
        )
    value = getattr(phases, request.phase, _MISSING)
    if request.phase not in phases.model_fields_set:
        if value is not None:
            raise _invalid_phase_input(
                "ownership value disagrees with declaration presence", request, source
            )
        return "unspecified", "phase_omitted"
    if value is None:
        return "unspecified", "phase_null"
    if type(value) is not str or value not in ("managed", "external", "disabled"):
        raise _invalid_phase_input(
            "requested ownership is not managed, external, disabled or null",
            request,
            source,
        )
    return value, "declared"


def analyze_phase_request(index: ResourceIndex, request: PhaseRequest) -> PhaseAnalysis:
    """Analyze one explicit phase; never inspect bindings, drivers or operations."""
    if not isinstance(request, PhaseRequest):
        raise PhaseAnalysisError(
            PhaseDiagnostic(
                "invalid_phase_request", "expected an explicit PhaseRequest"
            )
        )
    # Own a validated request, including when passed a subclass or altered record.
    request = PhaseRequest(request.resource_identity, request.phase)
    if not isinstance(index, ResourceIndex) or not isinstance(index.resources, Mapping):
        raise _invalid_phase_input(
            "expected ResourceIndex with a resource mapping", request
        )
    entry = index.resources.get(request.resource_identity)
    if entry is None and request.resource_identity not in index.resources:
        raise PhaseAnalysisError(
            PhaseDiagnostic(
                "unknown_phase_resource",
                "resource is not declared under the exact identity",
                request.resource_identity,
                request.phase,
            )
        )
    if not isinstance(entry, IndexedResource):
        raise _invalid_phase_input("missing indexed resource record", request)
    source = _source(entry.source, request)
    resource = entry.resource
    kind = getattr(resource, "kind", None)
    if (
        type(kind) is not str
        or kind not in _RESOURCE_TYPES
        or not isinstance(resource, _RESOURCE_TYPES[kind])
        or getattr(resource, "identity", None) != request.resource_identity
    ):
        raise _invalid_phase_input(
            "resource type or indexed identity mismatch", request, source
        )
    ownership, origin = _ownership(resource, request, source)
    capability = None
    if ownership == "managed":
        capability = CAPABILITY_VOCABULARY.get((kind, request.phase))
        if capability is None:
            raise PhaseAnalysisError(
                PhaseDiagnostic(
                    "unsupported_managed_phase",
                    "no documented capability mapping for this managed resource/phase",
                    request.resource_identity,
                    request.phase,
                    source,
                    ("lifecycle", "phases", request.phase),
                )
            )
    return PhaseAnalysis(PhaseFact(request, ownership, origin, capability), source)


@dataclass(frozen=True, slots=True)
class DriverSupportDiagnostic:
    code: Literal[
        "invalid_driver_descriptor",
        "duplicate_driver_descriptor",
        "duplicate_driver_capability",
        "invalid_support_query",
    ]
    message: str
    driver_id: str | None = None
    capability: str | None = None


class DriverSupportError(ValueError):
    def __init__(self, diagnostic: DriverSupportDiagnostic) -> None:
        self.diagnostic = diagnostic
        super().__init__(
            f"{diagnostic.code}; driver={diagnostic.driver_id}; "
            f"capability={diagnostic.capability}; {diagnostic.message}"
        )


def _support_name(value: object, *, query: bool = False) -> str:
    try:
        return _name_adapter.validate_python(value, strict=True)
    except ValidationError:
        raise DriverSupportError(
            DriverSupportDiagnostic(
                "invalid_support_query" if query else "invalid_driver_descriptor",
                "driver/capability identifiers must be strict nonempty "
                "slash/whitespace-free strings",
            )
        ) from None


@dataclass(frozen=True, slots=True)
class DriverSupportDescriptor:
    """Supplied declarations only, never a driver object or availability claim."""

    driver_id: str
    capabilities: tuple[str, ...]

    def __post_init__(self) -> None:
        driver = _support_name(self.driver_id)
        if not isinstance(self.capabilities, (list, tuple)):
            raise DriverSupportError(
                DriverSupportDiagnostic(
                    "invalid_driver_descriptor",
                    "capabilities must be an explicit list or tuple",
                    driver,
                )
            )
        capabilities = tuple(
            sorted(_support_name(value) for value in self.capabilities)
        )
        for a, b in zip(capabilities, capabilities[1:], strict=False):
            if a == b:
                raise DriverSupportError(
                    DriverSupportDiagnostic(
                        "duplicate_driver_capability",
                        "capability declared more than once",
                        driver,
                        a,
                    )
                )
        object.__setattr__(self, "driver_id", driver)
        object.__setattr__(self, "capabilities", capabilities)


@dataclass(frozen=True, slots=True)
class DriverSupportMetadata:
    """An owned canonical tuple of explicitly supplied descriptors; not discovery."""

    descriptors: tuple[DriverSupportDescriptor, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.descriptors, (list, tuple)) or any(
            not isinstance(value, DriverSupportDescriptor) for value in self.descriptors
        ):
            raise DriverSupportError(
                DriverSupportDiagnostic(
                    "invalid_driver_descriptor",
                    "metadata requires an explicit list or tuple of descriptors",
                )
            )
        descriptors = tuple(
            sorted(
                (
                    DriverSupportDescriptor(value.driver_id, value.capabilities)
                    for value in self.descriptors
                ),
                key=lambda value: value.driver_id,
            )
        )
        for a, b in zip(descriptors, descriptors[1:], strict=False):
            if a.driver_id == b.driver_id:
                raise DriverSupportError(
                    DriverSupportDiagnostic(
                        "duplicate_driver_descriptor",
                        "driver declared more than once",
                        a.driver_id,
                    )
                )
        object.__setattr__(self, "descriptors", descriptors)


@dataclass(frozen=True, slots=True)
class DriverSupportAssessment:
    driver_id: str
    capability: str
    status: SupportStatus


def assess_driver_support(
    metadata: DriverSupportMetadata, driver_id: str, capability: str
) -> DriverSupportAssessment:
    """Inspect supplied facts only; missing metadata is distinct from no support."""
    if not isinstance(metadata, DriverSupportMetadata):
        raise DriverSupportError(
            DriverSupportDiagnostic(
                "invalid_driver_descriptor",
                "expected explicitly supplied DriverSupportMetadata",
            )
        )
    driver = _support_name(driver_id, query=True)
    capability = _support_name(capability, query=True)
    status: SupportStatus = "metadata_unavailable"
    for descriptor in metadata.descriptors:
        if descriptor.driver_id == driver:
            status = (
                "declared_supported"
                if capability in descriptor.capabilities
                else "declared_unsupported"
            )
            break
    return DriverSupportAssessment(driver, capability, status)
