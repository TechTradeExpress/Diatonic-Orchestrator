"""Versioned common resource envelope, independent from provider execution."""

from typing import Literal

from pydantic import Field, JsonValue

from diatonic.model.lifecycle import Lifecycle, StrictModel
from diatonic.model.types import ResourceName, ResourceReference


class Metadata(StrictModel):
    """Shared resource metadata in iac/v0alpha1."""

    name: ResourceName
    description: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class ResourceBase(StrictModel):
    """Envelope only; kind-specific `spec` validation follows in M1.2+.

    This base model does not claim that arbitrary `kind` values are supported.
    Concrete kind models will narrow the discriminator and the spec type.
    """

    api_version: Literal["iac/v0alpha1"]
    kind: ResourceName
    metadata: Metadata
    spec: dict[str, JsonValue] | None = None
    lifecycle: Lifecycle | None = None
    depends_on: list[ResourceReference] = Field(default_factory=list)
    extensions: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)

    @property
    def identity(self) -> str:
        """Canonical logical ID; not serialized into user-facing model data."""
        return f"{self.kind}/{self.metadata.name}"
