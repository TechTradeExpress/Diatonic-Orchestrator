"""M1.2 VM core fragment; the full public VM schema is implemented later."""

from typing import Annotated, Literal

from pydantic import Field

from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import StrictModel


class CpuSpec(StrictModel):
    """Portable CPU allocation."""

    cores: Annotated[int, Field(gt=0)]


class MemorySpec(StrictModel):
    """Portable memory allocation in MiB."""

    mib: Annotated[int, Field(gt=0)]


class VirtualMachineSpec(StrictModel):
    """Only CPU and memory; placement, disks, interfaces and image are deferred."""

    cpu: CpuSpec
    memory: MemorySpec


class VirtualMachine(ResourceBase):
    """Initial typed VM resource, preserving the shared envelope."""

    kind: Literal["VirtualMachine"]
    spec: VirtualMachineSpec
