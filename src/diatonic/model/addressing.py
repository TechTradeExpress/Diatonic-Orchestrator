"""Syntax-only IP checks that preserve the declared string representation."""

from ipaddress import IPv4Address, IPv4Interface, IPv4Network, ip_address
from typing import Annotated

from pydantic import AfterValidator


def _ipv4_address(value: str) -> str:
    IPv4Address(value)
    return value


def _ip_address(value: str) -> str:
    if "%" in value:
        raise ValueError("management address must be an unscoped IP literal")
    ip_address(value)
    return value


def _require_prefix(value: str) -> None:
    address, separator, prefix = value.partition("/")
    if not address or not separator or not prefix.isascii() or not prefix.isdecimal():
        raise ValueError("must use IPv4 address/prefix-length notation")


def _ipv4_cidr(value: str) -> str:
    _require_prefix(value)
    IPv4Network(value, strict=True)
    return value


def _ipv4_interface(value: str) -> str:
    _require_prefix(value)
    IPv4Interface(value)
    return value


IPv4AddressString = Annotated[str, AfterValidator(_ipv4_address)]
IPAddressString = Annotated[str, AfterValidator(_ip_address)]
IPv4CidrString = Annotated[str, AfterValidator(_ipv4_cidr)]
IPv4InterfaceString = Annotated[str, AfterValidator(_ipv4_interface)]
