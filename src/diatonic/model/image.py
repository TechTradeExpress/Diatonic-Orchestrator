"""Portable image description, independent from vendor image identifiers."""

from typing import Annotated, Literal

from pydantic import Field

from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import StrictModel

ImageText = Annotated[str, Field(min_length=1)]


class OperatingSystemSpec(StrictModel):
    """Open string vocabulary; versions are never coerced from numbers."""

    family: ImageText
    distribution: ImageText
    version: ImageText
    architecture: ImageText


class ImageSpec(StrictModel):
    """Portable operating-system image attributes."""

    os: OperatingSystemSpec


class Image(ResourceBase):
    """A named image that providers may map to their own artifacts later."""

    kind: Literal["Image"]
    spec: ImageSpec
