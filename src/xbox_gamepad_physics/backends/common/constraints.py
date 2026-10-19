"""Engine-independent shaft-angle values consumed by backend adapters."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import math

from .model import Vec3, finite_value


def _unit_axis(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ValueError(f"shaft tilt limit {name} must be a unit vector")
    finite_value(value)
    if not math.isclose(sum(x*x for x in value), 1., rel_tol=0., abs_tol=1e-12):
        raise ValueError(f"shaft tilt limit {name} must be a unit vector")
    return tuple(float(x) for x in value)


@dataclass(frozen=True, slots=True)
class ShaftTiltLimit:
    """The shaft angle relative to a reference link must remain within a cone.

    Hard enforcement includes initialization, state writes and every physics
    substep, with no outward boundary velocity. Adapters supply the native
    frame bindings and solver. Descriptive metadata is not a runtime gate.
    """

    name: str
    reference_link: str
    moving_link: str
    reference_axis: Vec3
    moving_axis: Vec3
    maximum_rad: float

    def __post_init__(self):
        for name in ('name', 'reference_link', 'moving_link'):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise ValueError(f"shaft tilt limit {name} must be a non-empty name")
        for name in ('reference_axis', 'moving_axis'):
            object.__setattr__(self, name, _unit_axis(getattr(self, name), name))
        maximum = self.maximum_rad
        if isinstance(maximum, bool) or not isinstance(maximum, (int, float)):
            raise ValueError('Shaft limit angle must be a finite number in radians')
        finite_value(maximum)
        if not 0 < maximum < math.pi:
            raise ValueError('Shaft limit angle must be between zero and pi')

    @classmethod
    def from_record(cls, record: Mapping) -> ShaftTiltLimit:
        if not isinstance(record, Mapping):
            raise ValueError('A mechanical limit must be an object')
        if record.get('type') != 'shaft_tilt_limit' or record.get('enforcement') != 'hard':
            raise ValueError('Unsupported mechanical limit; hard enforcement is required')
        return cls(record.get('id'), record.get('reference_link'), record.get('moving_link'),
                   record.get('reference_axis'), record.get('moving_axis'),
                   record.get('max_angle_rad'))
