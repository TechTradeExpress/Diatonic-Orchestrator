"""Public envelope and initial typed resources for iac/v0alpha1."""

from diatonic.model.base import Metadata, ResourceBase
from diatonic.model.lifecycle import Lifecycle, Phases
from diatonic.model.resource import Resource, parse_resource
from diatonic.model.stage import Stage, StageSpec
from diatonic.model.types import ResourceName, ResourceReference
from diatonic.model.virtual_machine import (
    CpuSpec,
    MemorySpec,
    VirtualMachine,
    VirtualMachineSpec,
)

__all__ = [
    "CpuSpec",
    "Lifecycle",
    "Metadata",
    "MemorySpec",
    "Phases",
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
