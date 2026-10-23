"""Explicit dispatch for the resource kinds implemented in Milestone 1."""

from typing import Annotated

from pydantic import Field, TypeAdapter

from diatonic.model.hypervisor import Hypervisor
from diatonic.model.image import Image
from diatonic.model.network import Network
from diatonic.model.stage import Stage
from diatonic.model.virtual_machine import VirtualMachine

Resource = Annotated[
    Stage | Network | Hypervisor | Image | VirtualMachine, Field(discriminator="kind")
]
_resource_adapter = TypeAdapter(Resource)


def parse_resource(data: object) -> Resource:
    """Validate an already decoded document; unsupported kinds raise ValidationError."""
    return _resource_adapter.validate_python(data)
