"""Syntax-only validation for logical resource identifiers and references."""

from collections.abc import Callable
from typing import Annotated

from pydantic import AfterValidator


def _validate_segment(value: str) -> str:
    if not value or "/" in value or any(char.isspace() for char in value):
        raise ValueError("must be non-empty and contain no '/' or whitespace")
    return value


def _validate_reference(value: str) -> str:
    kind, separator, name = value.partition("/")
    if not separator:
        raise ValueError("must use canonical Kind/name syntax")
    _validate_segment(kind)
    _validate_segment(name)
    return value


ResourceName = Annotated[str, AfterValidator(_validate_segment)]
ResourceReference = Annotated[str, AfterValidator(_validate_reference)]


def _expected_kind(kind: str) -> Callable[[str], str]:
    def validate(value: str) -> str:
        if value.partition("/")[0] != kind:
            raise ValueError(f"reference must target {kind}/name")
        return value

    return validate


HypervisorReference = Annotated[
    ResourceReference, AfterValidator(_expected_kind("Hypervisor"))
]
NetworkReference = Annotated[
    ResourceReference, AfterValidator(_expected_kind("Network"))
]
ImageReference = Annotated[ResourceReference, AfterValidator(_expected_kind("Image"))]
