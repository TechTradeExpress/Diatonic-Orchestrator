"""Public envelope and portable resource types for iac/v0alpha1."""

from diatonic.model.base import Metadata, ResourceBase
from diatonic.model.hypervisor import Hypervisor, HypervisorSpec, ManagementSpec
from diatonic.model.image import Image, ImageSpec, OperatingSystemSpec
from diatonic.model.lifecycle import Lifecycle, Phases
from diatonic.model.network import Network, NetworkIPv4Spec, NetworkSpec
from diatonic.model.provider import Provider, ProviderSpec
from diatonic.model.provider_binding import (
    ProviderBinding,
    ProviderBindingMatch,
    ProviderBindingSpec,
)
from diatonic.model.resource import Resource, parse_resource
from diatonic.model.stage import Stage, StageSpec
from diatonic.model.types import ProviderReference, ResourceName, ResourceReference
from diatonic.model.virtual_machine import (
    CpuSpec,
    DiskSpec,
    ImageReferenceSpec,
    InterfaceIPv4Spec,
    InterfaceSpec,
    MemorySpec,
    PlacementSpec,
    VirtualMachine,
    VirtualMachineSpec,
)

__all__ = [
    "CpuSpec",
    "DiskSpec",
    "Hypervisor",
    "HypervisorSpec",
    "Image",
    "ImageReferenceSpec",
    "ImageSpec",
    "InterfaceIPv4Spec",
    "InterfaceSpec",
    "Lifecycle",
    "ManagementSpec",
    "Metadata",
    "MemorySpec",
    "Network",
    "NetworkIPv4Spec",
    "NetworkSpec",
    "OperatingSystemSpec",
    "Phases",
    "PlacementSpec",
    "Provider",
    "ProviderBinding",
    "ProviderBindingMatch",
    "ProviderBindingSpec",
    "ProviderReference",
    "ProviderSpec",
    "Resource",
    "ResourceBase",
    "ResourceName",
    "ResourceReference",
    "Stage",
    "StageSpec",
    "VirtualMachine",
    "VirtualMachineSpec",
    "parse_resource",
]
