"""Lifecycle declarations. Omitted values are not implicit managed ownership."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from diatonic.model.types import ResourceName

Ownership = Literal["managed", "external", "disabled"]
DesiredState = Literal["present", "absent"]


class StrictModel(BaseModel):
    """Reject unknown fields and implicit scalar coercion in resource documents."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Phases(StrictModel):
    """Explicit ownership declarations for initial lifecycle phases."""

    observe: Ownership | None = None
    provision: Ownership | None = None
    configure: Ownership | None = None


class Lifecycle(StrictModel):
    """Preserve unspecified lifecycle values until semantics are defined."""

    stage: ResourceName | None = None
    desired_state: DesiredState | None = None
    phases: Phases | None = None
    prevent_destroy: bool | None = None
