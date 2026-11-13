"""Portable named driver configuration, without discovery or execution."""

from typing import Literal

from pydantic import JsonValue

from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import StrictModel
from diatonic.model.types import ResourceName


class ProviderSpec(StrictModel):
    """Explicit driver ID and opaque JSON configuration; empty config is valid."""

    driver: ResourceName
    config: dict[str, JsonValue]


class Provider(ResourceBase):
    """A logical Provider instance, whose identity is independent of its driver."""

    kind: Literal["Provider"]
    # Pydantic replaces the envelope field with this required, validated spec.
    # Keep the base schema unchanged; see the contributing typing baseline.
    spec: ProviderSpec  # type: ignore[assignment]
