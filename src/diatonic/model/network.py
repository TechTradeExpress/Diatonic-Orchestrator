"""Portable network declaration, without network-service or provider fields."""

from typing import Annotated, Literal

from pydantic import Field

from diatonic.model.addressing import IPv4AddressString, IPv4CidrString
from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import StrictModel


class NetworkIPv4Spec(StrictModel):
    """Local syntax validation for the declared IPv4 subnet and gateway.

    The compiler's separate network-scoped IPv4 semantic pass checks membership;
    this schema does not perform those cross-field or cross-resource checks.
    """

    cidr: IPv4CidrString
    gateway: IPv4AddressString


class NetworkSpec(StrictModel):
    """Initial tagged IPv4 network schema."""

    vlan_id: Annotated[int, Field(ge=1, le=4094)]
    ipv4: NetworkIPv4Spec


class Network(ResourceBase):
    """A named portable network."""

    kind: Literal["Network"]
    # Pydantic replaces the envelope field with this required, validated spec.
    # Keep the base schema unchanged; see the contributing typing baseline.
    spec: NetworkSpec  # type: ignore[assignment]
