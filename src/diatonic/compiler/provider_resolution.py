"""Deterministic offline selection from explicit demand and supplied support facts."""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from pydantic import TypeAdapter, ValidationError

from diatonic.compiler.capabilities import (
    DriverSupportDescriptor,
    DriverSupportError,
    DriverSupportMetadata,
    PhaseAnalysis,
    PhaseAnalysisError,
    PhaseFact,
    PhaseRequest,
    PhaseSource,
    SupportStatus,
    analyze_phase_request,
    assess_driver_support,
)
from diatonic.compiler.provider_bindings import (
    BindingDeclaration,
    BindingSource,
    ValidatedProviderBindings,
)
from diatonic.compiler.references import (
    FieldPath,
    IndexedResource,
    ResourceIndex,
    SourceLocation,
)
from diatonic.model import (
    Metadata,
    Provider,
    ProviderBinding,
    ProviderBindingSpec,
    ProviderSpec,
)
from diatonic.model.types import ResourceName

_name_adapter = TypeAdapter(ResourceName)
ResolutionCode = Literal[
    "invalid_provider_resolution_input",
    "no_matching_provider_binding",
    "no_supported_provider_binding",
    "missing_driver_support_metadata",
    "ambiguous_provider_binding",
]
CandidateOutcome = Literal[
    "rejected",
    "metadata_unavailable",
    "unsupported",
    "supported_unresolved",
    "outranked",
    "selected",
    "ambiguous_highest_priority",
]


@dataclass(frozen=True, slots=True)
class ResolutionSource:
    """Detached document-root provenance, never an exact field coordinate."""

    source_path: Path
    document_index: int
    line: int | None
    column: int | None


@dataclass(frozen=True, slots=True)
class CandidateReason:
    code: Literal[
        "capability_mismatch",
        "kind_mismatch",
        "missing_label",
        "label_mismatch",
        "driver_metadata_unavailable",
        "driver_capability_unsupported",
        "lower_priority",
        "selection_uncertain",
        "highest_priority_tie",
        "selected_highest_priority",
    ]
    field_path: FieldPath
    expected: str | None = None
    actual: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "field_path", tuple(self.field_path))


@dataclass(frozen=True, slots=True)
class CandidateEvaluation:
    binding_identity: str
    provider_identity: str
    capability: str
    match_kind: str
    match_labels: Mapping[str, str]
    priority: int
    outcome: CandidateOutcome
    reasons: tuple[CandidateReason, ...]
    driver_id: str | None = None
    support_status: SupportStatus | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "match_labels", MappingProxyType(dict(self.match_labels))
        )
        object.__setattr__(self, "reasons", tuple(self.reasons))


@dataclass(frozen=True, slots=True)
class ProviderSelection:
    binding_identity: str
    provider_identity: str
    driver_id: str
    priority: int


@dataclass(frozen=True, slots=True)
class ResolutionFact:
    phase: PhaseFact
    status: Literal["selected", "external", "disabled", "unspecified"]
    selection: ProviderSelection | None
    candidates: tuple[CandidateEvaluation, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))


@dataclass(frozen=True, slots=True)
class ProviderResolution:
    fact: ResolutionFact
    sources: Mapping[str, ResolutionSource]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sources", MappingProxyType(dict(sorted(self.sources.items())))
        )


@dataclass(frozen=True, slots=True)
class ResolutionDiagnostic:
    code: ResolutionCode
    message: str
    phase: PhaseFact | None = None
    candidates: tuple[CandidateEvaluation, ...] = ()
    relevant_bindings: tuple[str, ...] = ()
    sources: Mapping[str, ResolutionSource] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidates", tuple(self.candidates))
        object.__setattr__(
            self, "relevant_bindings", tuple(sorted(self.relevant_bindings))
        )
        object.__setattr__(
            self, "sources", MappingProxyType(dict(sorted(self.sources.items())))
        )


class ProviderResolutionError(ValueError):
    def __init__(self, diagnostic: ResolutionDiagnostic) -> None:
        self.diagnostic = diagnostic
        details = [f"{diagnostic.code}: {diagnostic.message}"]
        if diagnostic.phase is not None:
            phase = diagnostic.phase
            details.append(
                f"resource={phase.request.resource_identity}; "
                f"phase={phase.request.phase}; capability={phase.required_capability}"
            )
        for candidate in diagnostic.candidates:
            if candidate.binding_identity in diagnostic.relevant_bindings:
                details.append(
                    f"binding={candidate.binding_identity}; "
                    f"provider={candidate.provider_identity}; "
                    f"driver={candidate.driver_id}; priority={candidate.priority}"
                )
        for identity, source in diagnostic.sources.items():
            location = f"{source.source_path} (document {source.document_index}"
            if source.line is not None:
                location += f", root line {source.line}"
            if source.column is not None:
                location += f", column {source.column}"
            details.append(f"{identity}: {location})")
        super().__init__("; ".join(details))


def _invalid(
    message: str,
    phase: PhaseFact | None = None,
    sources: Mapping[str, ResolutionSource] | None = None,
    binding: str | None = None,
) -> ProviderResolutionError:
    return ProviderResolutionError(
        ResolutionDiagnostic(
            "invalid_provider_resolution_input",
            message,
            phase,
            relevant_bindings=() if binding is None else (binding,),
            sources=sources or {},
        )
    )


def _source(value: object) -> ResolutionSource | None:
    if not isinstance(value, (SourceLocation, BindingSource, PhaseSource)) or (
        not isinstance(value.source_path, Path)
        or type(value.document_index) is not int
        or value.document_index < 1
        or any(
            v is not None and (type(v) is not int or v < 1)
            for v in (value.line, value.column)
        )
    ):
        return None
    return ResolutionSource(
        value.source_path, value.document_index, value.line, value.column
    )


def _phase_context(
    index: ResourceIndex, analysis: PhaseAnalysis
) -> tuple[PhaseFact, dict[str, ResolutionSource]]:
    if (
        not isinstance(analysis, PhaseAnalysis)
        or not isinstance(analysis.fact, PhaseFact)
        or not isinstance(analysis.fact.request, PhaseRequest)
    ):
        raise _invalid("expected an explicit successful PhaseAnalysis")
    if not isinstance(index, ResourceIndex) or not isinstance(index.resources, Mapping):
        raise _invalid("expected a matching ResourceIndex")
    try:
        current = analyze_phase_request(index, analysis.fact.request)
    except PhaseAnalysisError as error:
        source = _source(error.diagnostic.source)
        sources = (
            {error.diagnostic.resource_identity: source} if source is not None else {}
        )
        raise _invalid(
            f"requested analysis/index is inconsistent ({error.diagnostic.code}); "
            "analyze again",
            sources=sources,
        ) from None
    source = _source(current.source)
    if source is None:
        raise _invalid("missing requested resource provenance", current.fact)
    sources = {current.fact.request.resource_identity: source}
    if analysis != current:
        raise _invalid(
            "phase facts or provenance disagree with the current requested resource",
            current.fact,
            sources,
        )
    return current.fact, sources


def _binding_snapshot(
    index: ResourceIndex,
    bindings: ValidatedProviderBindings | None,
    phase: PhaseFact,
    sources: dict[str, ResolutionSource],
) -> tuple[BindingDeclaration, ...]:
    if not isinstance(bindings, ValidatedProviderBindings):
        raise _invalid(
            "managed demand requires ValidatedProviderBindings, "
            "including an explicit empty result",
            phase,
            sources,
        )
    if not isinstance(bindings.declarations, tuple) or not isinstance(
        bindings.sources, Mapping
    ):
        raise _invalid("malformed binding summary containers", phase, sources)
    if any(type(key) is not str for key in index.resources):
        raise _invalid("indexed identity keys must be strings", phase, sources)
    summaries = {}
    for declaration in bindings.declarations:
        if (
            not isinstance(declaration, BindingDeclaration)
            or any(
                type(value) is not str
                for value in (
                    declaration.resource_identity,
                    declaration.provider_identity,
                    declaration.capability,
                    declaration.match_kind,
                )
            )
            or type(declaration.priority) is not int
            or not isinstance(declaration.match_labels, Mapping)
            or any(
                type(k) is not str or type(v) is not str
                for k, v in declaration.match_labels.items()
            )
            or declaration.field_path != ("spec", "provider")
        ):
            raise _invalid("malformed binding declaration summary", phase, sources)
        if declaration.resource_identity in summaries:
            raise _invalid(
                "duplicate binding summary",
                phase,
                sources,
                declaration.resource_identity,
            )
        summaries[declaration.resource_identity] = declaration
    indexed = {
        identity
        for identity, entry in index.resources.items()
        if identity.startswith("ProviderBinding/")
        or (
            isinstance(entry, IndexedResource)
            and isinstance(entry.resource, ProviderBinding)
        )
    }
    if set(summaries) != indexed:
        raise _invalid(
            "binding summaries do not cover exactly the indexed bindings; "
            "validate again",
            phase,
            sources,
        )
    expected_sources = set()
    declarations = []
    for identity in sorted(indexed):
        entry = index.resources[identity]
        if (
            not isinstance(entry, IndexedResource)
            or not isinstance(entry.resource, ProviderBinding)
            or getattr(entry.resource, "identity", None) != identity
        ):
            raise _invalid(
                "binding type or indexed identity mismatch", phase, sources, identity
            )
        source = (
            _source(entry.source) if isinstance(entry.source, SourceLocation) else None
        )
        if source is None:
            raise _invalid(
                "missing binding document-root provenance", phase, sources, identity
            )
        sources[identity] = source
        spec = getattr(entry.resource, "spec", None)
        if not isinstance(spec, ProviderBindingSpec):
            raise _invalid(
                "binding no longer has a typed spec", phase, sources, identity
            )
        try:
            spec = ProviderBindingSpec.model_validate(spec.model_dump(warnings=False))
        except ValidationError:
            raise _invalid(
                "binding spec no longer satisfies its schema", phase, sources, identity
            ) from None
        expected = BindingDeclaration(
            identity,
            spec.provider,
            spec.capability,
            spec.match.kind,
            dict(sorted(spec.match.labels.items())),
            spec.priority,
        )
        if summaries[identity] != expected:
            raise _invalid(
                "binding summary is stale or inconsistent with indexed spec",
                phase,
                sources,
                identity,
            )
        target = index.resources.get(spec.provider)
        if (
            not isinstance(target, IndexedResource)
            or not isinstance(target.resource, Provider)
            or getattr(target.resource, "identity", None) != spec.provider
        ):
            raise _invalid(
                "binding target is missing or not a typed Provider "
                "with the indexed identity",
                phase,
                sources,
                identity,
            )
        provider_source = (
            _source(target.source)
            if isinstance(target.source, SourceLocation)
            else None
        )
        if provider_source is None:
            raise _invalid(
                "missing Provider document-root provenance", phase, sources, identity
            )
        sources[spec.provider] = provider_source
        for key in (identity, spec.provider):
            provided = bindings.sources.get(key)
            if (
                not isinstance(provided, BindingSource)
                or _source(provided) != sources[key]
            ):
                raise _invalid(
                    "binding/index provenance mismatch", phase, sources, identity
                )
            expected_sources.add(key)
        declarations.append(expected)
    if set(bindings.sources) != expected_sources:
        raise _invalid(
            "binding source mapping contains missing or stale identities",
            phase,
            sources,
        )
    return tuple(declarations)


def _metadata(
    metadata: DriverSupportMetadata | None,
    phase: PhaseFact,
    sources: Mapping[str, ResolutionSource],
) -> DriverSupportMetadata:
    if metadata is None:
        return DriverSupportMetadata(())
    if not isinstance(metadata, DriverSupportMetadata):
        raise _invalid(
            "expected supplied DriverSupportMetadata or None", phase, sources
        )
    values = getattr(metadata, "descriptors", None)
    if not isinstance(values, (tuple, list)) or any(
        not isinstance(v, DriverSupportDescriptor) for v in values
    ):
        raise _invalid("malformed driver metadata descriptors", phase, sources)
    try:
        return DriverSupportMetadata(
            tuple(
                DriverSupportDescriptor(
                    getattr(v, "driver_id", None), getattr(v, "capabilities", None)
                )
                for v in values
            )
        )
    except DriverSupportError:
        raise _invalid(
            "supplied driver metadata no longer satisfies M2.7 validation",
            phase,
            sources,
        ) from None


def _matching_reasons(
    declaration: BindingDeclaration,
    kind: str,
    labels: Mapping[str, str],
    capability: str,
) -> tuple[CandidateReason, ...]:
    reasons = []
    if declaration.capability != capability:
        reasons.append(
            CandidateReason(
                "capability_mismatch",
                ("spec", "capability"),
                capability,
                declaration.capability,
            )
        )
    if declaration.match_kind != kind:
        reasons.append(
            CandidateReason(
                "kind_mismatch", ("spec", "match", "kind"), kind, declaration.match_kind
            )
        )
    for key, value in declaration.match_labels.items():
        if key not in labels:
            reasons.append(
                CandidateReason(
                    "missing_label", ("spec", "match", "labels", key), value
                )
            )
        elif labels[key] != value:
            reasons.append(
                CandidateReason(
                    "label_mismatch",
                    ("spec", "match", "labels", key),
                    value,
                    labels[key],
                )
            )
    return tuple(reasons)


def _evaluate(
    index: ResourceIndex,
    phase: PhaseFact,
    declarations: tuple[BindingDeclaration, ...],
    metadata: DriverSupportMetadata,
    sources: Mapping[str, ResolutionSource],
) -> tuple[CandidateEvaluation, ...]:
    resource = index.resources[phase.request.resource_identity].resource
    resource_metadata = getattr(resource, "metadata", None)
    labels = getattr(resource_metadata, "labels", None)
    if (
        not isinstance(resource_metadata, Metadata)
        or not isinstance(labels, dict)
        or any(type(k) is not str or type(v) is not str for k, v in labels.items())
    ):
        raise _invalid(
            "requested metadata labels must be a validated string mapping",
            phase,
            sources,
        )
    labels = dict(labels)
    support_cache = {}
    candidates = []
    for declaration in declarations:
        reasons = _matching_reasons(
            declaration, resource.kind, labels, phase.required_capability
        )
        driver = None
        support = None
        outcome: CandidateOutcome = "rejected"
        if not reasons:
            provider = index.resources[declaration.provider_identity].resource
            spec = getattr(provider, "spec", None)
            if not isinstance(spec, ProviderSpec):
                raise _invalid(
                    "matching Provider must have a typed spec",
                    phase,
                    sources,
                    declaration.resource_identity,
                )
            try:
                # Only the driver ID is read; config is neither inspected nor retained.
                driver = _name_adapter.validate_python(
                    getattr(spec, "driver", None), strict=True
                )
            except ValidationError:
                raise _invalid(
                    "matching Provider driver ID is invalid",
                    phase,
                    sources,
                    declaration.resource_identity,
                ) from None
            if driver not in support_cache:
                support_cache[driver] = assess_driver_support(
                    metadata, driver, phase.required_capability
                ).status
            support = support_cache[driver]
            if support == "metadata_unavailable":
                outcome = "metadata_unavailable"
                reasons = (
                    CandidateReason(
                        "driver_metadata_unavailable", ("spec", "provider")
                    ),
                )
            elif support == "declared_unsupported":
                outcome = "unsupported"
                reasons = (
                    CandidateReason(
                        "driver_capability_unsupported", ("spec", "provider")
                    ),
                )
            else:
                outcome = "supported_unresolved"
        candidates.append(
            CandidateEvaluation(
                declaration.resource_identity,
                declaration.provider_identity,
                declaration.capability,
                declaration.match_kind,
                declaration.match_labels,
                declaration.priority,
                outcome,
                reasons,
                driver,
                support,
            )
        )
    return tuple(candidates)


def resolve_phase_provider(
    index: ResourceIndex,
    analysis: PhaseAnalysis,
    bindings: ValidatedProviderBindings | None = None,
    metadata: DriverSupportMetadata | None = None,
) -> ProviderResolution:
    """Resolve explicit managed demand from offline declarations only."""
    phase, sources = _phase_context(index, analysis)
    if phase.ownership != "managed":
        return ProviderResolution(
            ResolutionFact(phase, phase.ownership, None, ()), sources
        )
    declarations = _binding_snapshot(index, bindings, phase, sources)
    metadata = _metadata(metadata, phase, sources)
    candidates = _evaluate(index, phase, declarations, metadata, sources)
    supported = [c for c in candidates if c.support_status == "declared_supported"]
    unknown = [c for c in candidates if c.support_status == "metadata_unavailable"]
    highest = max((c.priority for c in supported), default=None)
    decisive = [c for c in unknown if highest is None or c.priority >= highest]
    top = [c for c in supported if c.priority == highest]

    if not any(c.support_status is not None for c in candidates):
        code: ResolutionCode | None = "no_matching_provider_binding"
        message = "no binding matches the requested capability, kind and labels"
        relevant = ()
    elif decisive:
        code = "missing_driver_support_metadata"
        message = (
            "unknown driver support could change the winner or highest-priority tie"
        )
        relevant = tuple(c.binding_identity for c in decisive)
    elif not supported:
        code = "no_supported_provider_binding"
        message = "all structurally matching bindings have declared-unsupported drivers"
        relevant = tuple(
            c.binding_identity for c in candidates if c.support_status is not None
        )
    elif len(top) > 1:
        code = "ambiguous_provider_binding"
        message = (
            "multiple declared-supported bindings tie at highest priority, "
            "including same-Provider ties"
        )
        relevant = tuple(c.binding_identity for c in top)
    else:
        code = None
        message = ""
        relevant = ()

    final = []
    for candidate in candidates:
        if candidate.support_status == "declared_supported":
            if candidate.priority != highest:
                outcome, reason = "outranked", "lower_priority"
            elif code == "missing_driver_support_metadata":
                outcome, reason = "supported_unresolved", "selection_uncertain"
            elif code == "ambiguous_provider_binding":
                outcome, reason = "ambiguous_highest_priority", "highest_priority_tie"
            else:
                outcome, reason = "selected", "selected_highest_priority"
            candidate = replace(
                candidate,
                outcome=outcome,
                reasons=(
                    *candidate.reasons,
                    CandidateReason(reason, ("spec", "priority")),
                ),
            )
        elif (
            candidate.support_status == "metadata_unavailable"
            and highest is not None
            and candidate.priority < highest
        ):
            candidate = replace(
                candidate,
                reasons=(
                    *candidate.reasons,
                    CandidateReason("lower_priority", ("spec", "priority")),
                ),
            )
        final.append(candidate)
    trace = tuple(final)
    if code is not None:
        raise ProviderResolutionError(
            ResolutionDiagnostic(code, message, phase, trace, relevant, sources)
        )
    winner = top[0]
    selection = ProviderSelection(
        winner.binding_identity,
        winner.provider_identity,
        winner.driver_id,
        winner.priority,
    )
    return ProviderResolution(
        ResolutionFact(phase, "selected", selection, trace), sources
    )
