"""Platform-independent hypervisor resource."""

from typing import Literal

from diatonic.model.addressing import IPAddressString
from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import StrictModel


class ManagementSpec(StrictModel):
    """Management IP literal; no endpoint, protocol or credentials."""

    address: IPAddressString


class HypervisorSpec(StrictModel):
    """Portable management declaration."""

    management: ManagementSpec


class Hypervisor(ResourceBase):
    """A hypervisor with inherited explicit lifecycle ownership."""

    kind: Literal["Hypervisor"]
    spec: HypervisorSpec
