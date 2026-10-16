"""Camera/HDR intent; renderer realization is a backend responsibility."""
from dataclasses import dataclass
from ..backends.common.model import Pose


@dataclass(frozen=True)
class ViewSpec:
    reference_id: str
    root_pose: Pose
    joint_positions: dict
    camera_pose: Pose
    target: tuple
    up: tuple
    projection: str
    vertical_fov_rad: float
    resolution: tuple[int,int]
    hdri_identity: str | None
    hdri_pose: Pose
    intensity: float | None
    exposure: float | None
    background: object
