"""Engine-independent values, frames and traceable physical parameters."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Literal

Vec3 = tuple[float, float, float]
QuatWXYZ = tuple[float, float, float, float]
Mat3 = tuple[Vec3, Vec3, Vec3]
RootMode = Literal["fixed", "free"]


def finite_value(value: object) -> None:
    """Reject non-numeric leaves and non-finite physical values."""
    if isinstance(value, (list, tuple)):
        for item in value:
            finite_value(item)
    elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("physical values must contain finite numbers, excluding booleans")


@dataclass(frozen=True)
class Pose:
    position_m: Vec3 = (0.0, 0.0, 0.0)
    orientation_wxyz: QuatWXYZ = (1.0, 0.0, 0.0, 0.0)

    def __post_init__(self):
        finite_value(self.position_m)
        finite_value(self.orientation_wxyz)
        if len(self.position_m) != 3 or len(self.orientation_wxyz) != 4:
            raise ValueError("Pose requires a position triple and wxyz quaternion")
        if not math.isclose(sum(v * v for v in self.orientation_wxyz), 1.0, abs_tol=1e-12):
            raise ValueError("Pose quaternion must be normalized")


@dataclass(frozen=True)
class Evidence:
    source: str
    locator: str
    applicability: str
    derivation: str
    assumptions: tuple[str, ...] = ()
    category: str = "simulation_estimate"
    uncertainty: object | None = None
    uncertainty_reason: str | None = "No quantified uncertainty is available."

    def __post_init__(self):
        if not all(isinstance(v, str) and v for v in (self.source, self.locator, self.applicability, self.derivation)):
            raise ValueError("evidence requires source, locator, applicability and derivation")
        if self.category not in {"measurement", "proxy", "simulation_estimate", "legacy_numerical_assumption", "fixture_definition", "unknown"}:
            raise ValueError("unsupported evidence category")
        if self.uncertainty is None and not self.uncertainty_reason:
            raise ValueError("unknown uncertainty requires a reason")


@dataclass(frozen=True)
class Parameter:
    value: object | None
    unit: str
    evidence: tuple[Evidence, ...] = ()
    missing_reason: str | None = None

    def __post_init__(self):
        if not isinstance(self.unit, str) or not self.unit:
            raise ValueError("parameter requires an explicit unit")
        if self.value is None:
            if not self.missing_reason:
                raise ValueError("null parameter requires missing_reason")
        else:
            finite_value(self.value)
            if not self.evidence:
                raise ValueError("known parameter requires evidence")

    def as_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> Parameter:
        return cls(raw.get("value"), raw["unit"], tuple(Evidence(**{**item, "assumptions": tuple(item.get("assumptions", ()))}) for item in raw.get("evidence", ())), raw.get("missing_reason"))
