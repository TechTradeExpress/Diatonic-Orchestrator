"""Network-scoped IPv4 checks over an already validated, resolved resource index."""

from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Interface, IPv4Network
from typing import Literal

from diatonic.compiler.references import FieldPath, ResourceIndex, SourceLocation
from diatonic.model import Network, VirtualMachine


@dataclass(frozen=True)
class IPv4Declaration:
    """Owner and document-root origin of a conflicting address declaration."""

    resource_identity: str
    field_path: FieldPath
    source: SourceLocation
    address: str


@dataclass(frozen=True)
class IPv4Diagnostic:
    """A semantic failure with logical-network and declared address context."""

    code: Literal[
        "gateway_outside_subnet",
        "address_outside_subnet",
        "duplicate_static_ipv4",
        "gateway_address_conflict",
    ]
    message: str
    resource_identity: str
    field_path: FieldPath
    source: SourceLocation
    network_identity: str
    cidr: str
    address: str
    related: IPv4Declaration | None = None


class SemanticValidationError(ValueError):
    """One fail-fast IPv4 diagnostic; no mutation or partial result."""

    def __init__(self, diagnostic: IPv4Diagnostic) -> None:
        self.diagnostic = diagnostic
        related = (
            f"; conflicting declaration: {diagnostic.related}"
            if diagnostic.related is not None
            else ""
        )
        super().__init__(
            f"{diagnostic.source}: {diagnostic.code}: {diagnostic.resource_identity} "
            f"at {diagnostic.field_path}: {diagnostic.message}; "
            f"network={diagnostic.network_identity}; cidr={diagnostic.cidr}; "
            f"address={diagnostic.address}{related}"
        )


def validate_ipv4_semantics(index: ResourceIndex) -> None:
    """Check all Network gateways, then VM static hosts, in canonical owner order.

    Requires a successful, unmodified resolver result. Syntax and reference-kind
    validation belong to earlier stages. Interface prefixes need not match CIDRs.
    """
    if not isinstance(index, ResourceIndex):
        raise TypeError("validate_ipv4_semantics requires a ResourceIndex")
    identities = sorted(index.resources)
    networks: dict[str, tuple[IPv4Network, IPv4Address, str]] = {}
    for identity in identities:
        entry = index.resources[identity]
        resource = entry.resource
        if not isinstance(resource, Network):
            continue
        ipv4 = resource.spec.ipv4
        subnet, gateway = IPv4Network(ipv4.cidr), IPv4Address(ipv4.gateway)
        if gateway not in subnet:
            raise SemanticValidationError(
                IPv4Diagnostic(
                    code="gateway_outside_subnet",
                    message="gateway is outside its declared subnet",
                    resource_identity=identity,
                    field_path=("spec", "ipv4", "gateway"),
                    source=entry.source,
                    network_identity=identity,
                    cidr=ipv4.cidr,
                    address=ipv4.gateway,
                )
            )
        networks[identity] = subnet, gateway, ipv4.cidr

    seen: dict[tuple[str, IPv4Address], IPv4Declaration] = {}
    for identity in identities:
        entry = index.resources[identity]
        if not isinstance(entry.resource, VirtualMachine):
            continue
        for i, interface in enumerate(entry.resource.spec.interfaces):
            if interface.ipv4 is None or interface.ipv4.mode != "static":
                continue
            address = interface.ipv4.address
            host = IPv4Interface(address).ip
            network = interface.network
            subnet, gateway, cidr = networks[network]
            path: FieldPath = ("spec", "interfaces", i, "ipv4", "address")
            declaration = IPv4Declaration(identity, path, entry.source, address)
            if host not in subnet:
                raise SemanticValidationError(
                    IPv4Diagnostic(
                        code="address_outside_subnet",
                        message=f"static host {host} is outside the referenced subnet",
                        resource_identity=identity,
                        field_path=path,
                        source=entry.source,
                        network_identity=network,
                        cidr=cidr,
                        address=address,
                    )
                )
            if host == gateway:
                network_source = index.resources[network].source
                raise SemanticValidationError(
                    IPv4Diagnostic(
                        code="gateway_address_conflict",
                        message=f"static host {host} equals the declared gateway",
                        resource_identity=identity,
                        field_path=path,
                        source=entry.source,
                        network_identity=network,
                        cidr=cidr,
                        address=address,
                        related=IPv4Declaration(
                            network,
                            ("spec", "ipv4", "gateway"),
                            network_source,
                            str(gateway),
                        ),
                    )
                )
            key = network, host
            if key in seen:
                raise SemanticValidationError(
                    IPv4Diagnostic(
                        code="duplicate_static_ipv4",
                        message=f"static host {host} is assigned more than once "
                        "in this logical network",
                        resource_identity=identity,
                        field_path=path,
                        source=entry.source,
                        network_identity=network,
                        cidr=cidr,
                        address=address,
                        related=seen[key],
                    )
                )
            seen[key] = declaration
