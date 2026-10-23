"""Portable network declaration, without network-service or provider fields."""

from typing import Annotated, Literal

from pydantic import Field

from diatonic.model.addressing import IPv4AddressString, IPv4CidrString
from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import StrictModel


class NetworkIPv4Spec(StrictModel):
    """Declared IPv4 subnet and gateway; membership checks are deferred."""

    cidr: IPv4CidrString
    gateway: IPv4AddressString


class NetworkSpec(StrictModel):
    """Initial tagged IPv4 network schema."""

    vlan_id: Annotated[int, Field(ge=1, le=4094)]
    ipv4: NetworkIPv4Spec


class Network(ResourceBase):
    """A named portable network."""

    kind: Literal["Network"]
    spec: NetworkSpec
