"""Typed stage declaration; ordering semantics belong to later milestones."""

from typing import Literal

from diatonic.model.base import ResourceBase
from diatonic.model.lifecycle import StrictModel


class StageSpec(StrictModel):
    """Explicit order, without an undocumented positivity constraint."""

    order: int


class Stage(ResourceBase):
    """A named coarse orchestration boundary."""

    kind: Literal["Stage"]
    spec: StageSpec
