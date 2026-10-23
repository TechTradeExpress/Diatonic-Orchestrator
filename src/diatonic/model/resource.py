"""Explicit dispatch for the resource kinds implemented in M1.2."""

from typing import Annotated

from pydantic import Field, TypeAdapter

from diatonic.model.stage import Stage
from diatonic.model.virtual_machine import VirtualMachine

Resource = Annotated[Stage | VirtualMachine, Field(discriminator="kind")]
_resource_adapter = TypeAdapter(Resource)


def parse_resource(data: object) -> Resource:
    """Validate an already decoded document; unsupported kinds raise ValidationError."""
    return _resource_adapter.validate_python(data)
