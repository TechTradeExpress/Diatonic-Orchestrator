"""Portable ProviderBinding declarations, without selector evaluation or selection."""

from typing import Annotated, Literal

from pydantic import AfterValidator, Field

from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import StrictModel
from diatonic.model.types import ProviderReference, ResourceName


def _exact_selector(value: str) -> str:
    # A deliberately small literal grammar; no globs, comparisons or boolean ops.
    if any(char in "*?[]!=<>|&" for char in value):
        raise ValueError("selector wildcards and operators are not supported")
    return value


_SelectorLabel = Annotated[str, AfterValidator(_exact_selector)]


class ProviderBindingMatch(StrictModel):
    """Future exact kind and conjunctive label equality; no matching occurs here."""

    kind: Annotated[ResourceName, AfterValidator(_exact_selector)]
    labels: dict[_SelectorLabel, _SelectorLabel] = Field(default_factory=dict)


class ProviderBindingSpec(StrictModel):
    capability: ResourceName
    match: ProviderBindingMatch
    provider: ProviderReference
    priority: int


class ProviderBinding(ResourceBase):
    kind: Literal["ProviderBinding"]
    spec: ProviderBindingSpec
