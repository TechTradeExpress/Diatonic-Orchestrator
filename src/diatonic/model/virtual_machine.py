"""Portable VM specification with syntax-only resource references."""

from typing import Annotated, Literal

from pydantic import Field

from diatonic.model.addressing import IPv4InterfaceString
from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import StrictModel
from diatonic.model.types import (
    HypervisorReference,
    ImageReference,
    NetworkReference,
    ResourceName,
)


class CpuSpec(StrictModel):
    """Portable CPU allocation."""

    cores: Annotated[int, Field(gt=0)]


class MemorySpec(StrictModel):
    """Portable memory allocation in MiB."""

    mib: Annotated[int, Field(gt=0)]


class PlacementSpec(StrictModel):
    """Target kind and syntax only; resource existence is checked later."""

    target: HypervisorReference


class DiskSpec(StrictModel):
    """Named disk allocation in whole GiB."""

    name: ResourceName
    size_gib: Annotated[int, Field(gt=0)]


class InterfaceIPv4Spec(StrictModel):
    """The static IPv4 declaration demonstrated by the public contract."""

    mode: Literal["static"]
    address: IPv4InterfaceString


class InterfaceSpec(StrictModel):
    """Named network attachment, optionally with explicit IPv4 configuration."""

    name: ResourceName
    network: NetworkReference
    ipv4: InterfaceIPv4Spec | None = None


class ImageReferenceSpec(StrictModel):
    """Logical image reference without platform-specific image IDs."""

    ref: ImageReference


class VirtualMachineSpec(StrictModel):
    """CPU/memory stay required; additional sections preserve M1.2 compatibility."""

    cpu: CpuSpec
    memory: MemorySpec
    placement: PlacementSpec | None = None
    disks: list[DiskSpec] = Field(default_factory=list)
    interfaces: list[InterfaceSpec] = Field(default_factory=list)
    image: ImageReferenceSpec | None = None


class VirtualMachine(ResourceBase):
    """Typed VM resource, preserving the shared envelope."""

    kind: Literal["VirtualMachine"]
    spec: VirtualMachineSpec
