"""RoboTwin-only projection of neutral return laws and contact policies."""
from __future__ import annotations
from ..backends.common.calibration import ResolvedCalibration
from ..backends.common.model import Parameter


def calibrated_contact(source: dict, calibration: ResolvedCalibration | None = None) -> dict:
    contact = dict(source["contact_material"])
    if calibration is not None:
        for path, parameter in calibration.physical.items():
            if path.startswith("contact_materials."):
                _, material, key = path.split(".")
                if material != "controller":
                    raise ValueError(f"{path}: unknown material")
                if key in {"rolling_resistance_length", "torsional_resistance_length"}:
                    if parameter.value is not None:
                        raise ValueError(f"{path}: RoboTwin has no verified mapping for this contact field")
                else:
                    if parameter.value is None:
                        raise ValueError(f"{path}: RoboTwin requires an explicit value; simulator defaults are not a fallback")
                    contact[key] = parameter.value
    if calibration is not None:
        for key in ("contact_offset_m", "rest_offset_m"):
            if key in calibration.backend_options.get("robotwin", {}):
                parameter = Parameter.from_dict(calibration.backend_options["robotwin"][key])
                if parameter.unit != "m" or parameter.value is None or parameter.value < 0:
                    raise ValueError(f"robotwin.{key}: requires a known nonnegative length")
                contact[key] = parameter.value
        if contact["rest_offset_m"] > contact["contact_offset_m"]:
            raise ValueError("robotwin contact offset must be at least the rest offset")
    return contact


def require_robotwin_dynamics(records: dict, calibration: ResolvedCalibration | None) -> None:
    """Validate the backend mapping before writing any output files."""
    for name, record in records.items():
        for key in ("stiffness", "drive_damping", "passive_damping", "effort", "target"):
            if record[key] is None:
                raise ValueError(f"joints.{name}.{key}: RoboTwin requires an explicit value; simulator defaults are not a fallback")
        if "dry_friction_effort" in record and record["dry_friction_effort"] is not None:
            raise ValueError(f"joints.{name}.dry_friction_effort: no verified mapping to the dimensionless PhysX friction coefficient")
    if calibration is not None:
        options = calibration.backend_options.get("robotwin", {})
        unknown = set(options) - {"joint_friction_coefficients", "contact_offset_m", "rest_offset_m"}
        if unknown:
            raise ValueError(f"unsupported robotwin calibration options: {sorted(unknown)}")
        for name, value in options.get("joint_friction_coefficients", {}).items():
            parameter = Parameter.from_dict(value)
            if name not in records or parameter.unit != "1" or parameter.value is None or parameter.value < 0:
                raise ValueError(f"robotwin.joint_friction_coefficients.{name}: requires a known nonnegative dimensionless value")
            records[name]["friction"] = parameter.value



def configure_robotwin_dynamics(records, source, profile, calibration=None):
    """Keep historical PhysX coefficients separate from neutral dry friction."""
    for name,record in records.items():
        if profile == "left_stick":
            record["friction"] = float(source["passive_dynamics"]["joint_friction_nm"])
        else:
            record["friction"] = (float(source["control_groups"]["sticks"]["tilt_joint_friction_coefficient"])
                                  if name in {"left_stick_x","left_stick_y","right_stick_x","right_stick_y"} else 0.0)
    require_robotwin_dynamics(records, calibration)
    return records
