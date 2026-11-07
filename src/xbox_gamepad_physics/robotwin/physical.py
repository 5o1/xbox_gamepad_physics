"""RoboTwin-only projection of neutral return laws and contact policies."""
from __future__ import annotations
from ..backends.common.calibration import ResolvedCalibration
from ..backends.common.model import Parameter

# Distribution dependency, not an asset readiness flag. a1 exports the same
# setter name but does not enable the native swing motions.
NATIVE_D6_SAPIEN_VERSION = "3.0.3+concon.physx5.6.1.a3"
NATIVE_D6_COMPATIBLE_VERSIONS = ("3.0.3+concon.physx5.6.1.a2", NATIVE_D6_SAPIEN_VERSION)


def require_native_cone_engine(policy, installed):
    if policy.get("mechanism") == "native_d6_cone" and installed not in NATIVE_D6_COMPATIBLE_VERSIONS:
        raise ValueError(f"native_d6_cone requires sapien=={NATIVE_D6_SAPIEN_VERSION} (validated a2 also supported) with the swing-motion fix; installed {installed}. a1/stock set_limit_cone is incompatible.")


def viscous_mapping(options):
    value = options.get("joint_friction_viscous_mapping", "native_friction")
    if not isinstance(value, str) or value not in {"native_friction", "drive_damping"}:
        raise ValueError("robotwin.joint_friction_viscous_mapping: expected native_friction or drive_damping")
    return value


def solver_iterations(options):
    if "solver_iterations" not in options:
        return None
    raw = options["solver_iterations"]
    if not isinstance(raw, dict) or set(raw) != {"position", "velocity"}:
        raise ValueError("robotwin.solver_iterations requires explicit position and velocity Parameters")
    values = []
    for key in ("position", "velocity"):
        p = Parameter.from_dict(raw[key])
        if p.unit != "1" or isinstance(p.value, bool) or not isinstance(p.value, int) or p.value < 1:
            raise ValueError(f"robotwin.solver_iterations.{key}: requires positive integer, unit1")
        values.append(p.value)
    return tuple(values)


def joint_friction_params(raw, joint_units):
    """Resolve explicit dimensional native friction, preserving legacy absence."""
    import math
    if not isinstance(raw, dict):
        raise ValueError("robotwin.joint_friction_params must be an object keyed by joint name")
    result = {}
    fields = ("static_effort", "dynamic_effort", "viscous")
    for name, record in raw.items():
        path = f"robotwin.joint_friction_params.{name}"
        if name not in joint_units:
            raise ValueError(f"{path}: unknown joint")
        if joint_units[name] not in {"m", "rad"}:
            raise ValueError(f"{path}: unsupported joint coordinate unit {joint_units[name]!r}")
        if not isinstance(record, dict) or set(record) != set(fields):
            raise ValueError(f"{path}: requires exactly static_effort, dynamic_effort, viscous")
        linear = joint_units[name] == "m"
        units = ("N", "N", "N*s/m") if linear else ("N*m", "N*m", "N*m*s/rad")
        values = []
        for field, unit in zip(fields, units):
            try:
                p = Parameter.from_dict(record[field])
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"{path}.{field}: invalid explicit Parameter: {error}") from error
            if p.unit != unit or p.value is None or isinstance(p.value, bool) or not isinstance(p.value, (int, float)) or not math.isfinite(p.value) or p.value < 0:
                raise ValueError(f"{path}.{field}: requires known finite nonnegative {unit}")
            values.append(float(p.value))
        if values[0] < values[1]:
            raise ValueError(f"{path}: static_effort must be >= dynamic_effort")
        result[name] = tuple(values)
    return result


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


def require_robotwin_dynamics(records: dict, calibration: ResolvedCalibration | None, *, default_options=None) -> None:
    """Validate the backend mapping before writing any output files."""
    for name, record in records.items():
        for key in ("stiffness", "drive_damping", "passive_damping", "effort", "target"):
            if record[key] is None:
                raise ValueError(f"joints.{name}.{key}: RoboTwin requires an explicit value; simulator defaults are not a fallback")
        if "dry_friction_effort" in record and record["dry_friction_effort"] is not None:
            raise ValueError(f"joints.{name}.dry_friction_effort: no verified mapping to the dimensionless PhysX friction coefficient")
    options = dict(default_options or {})
    if calibration is not None:
        overrides = calibration.backend_options.get("robotwin", {})
        if not isinstance(overrides, dict):
            raise ValueError("backend_options.robotwin must be an object")
        options.update(overrides)
    if options:
        if not isinstance(options, dict):
            raise ValueError("backend_options.robotwin must be an object")
        unknown = set(options) - {"joint_friction_coefficients", "joint_friction_params", "joint_friction_viscous_mapping", "solver_iterations", "shaft_tilt_limit", "stick_click_preload", "contact_offset_m", "rest_offset_m"}
        if unknown:
            raise ValueError(f"unsupported robotwin calibration options: {sorted(unknown)}")
        viscous_mapping(options)
        solver_iterations(options)
        for name, value in options.get("joint_friction_coefficients", {}).items():
            parameter = Parameter.from_dict(value)
            if name not in records or parameter.unit != "1" or parameter.value is None or parameter.value < 0:
                raise ValueError(f"robotwin.joint_friction_coefficients.{name}: requires a known nonnegative dimensionless value")
            records[name]["friction"] = parameter.value
        params = joint_friction_params(options.get("joint_friction_params", {}),
                                       {n: r.get("unit", "rad") for n, r in records.items()})
        for name in params:
            if name in options.get("joint_friction_coefficients", {}):
                raise ValueError(f"{name}: choose dimensional friction or legacy coefficient, not both")
            records[name]["friction"] = 0.0



def configure_robotwin_dynamics(records, source, profile, calibration=None):
    """Keep historical PhysX coefficients separate from neutral dry friction."""
    for name,record in records.items():
        if profile == "left_stick":
            record["friction"] = float(source["passive_dynamics"]["joint_friction_nm"])
        else:
            record["friction"] = (float(source["control_groups"]["sticks"]["tilt_joint_friction_coefficient"])
                                  if name in {"left_stick_x","left_stick_y","right_stick_x","right_stick_y"} else 0.0)
    defaults = source.get("backend_options", {}).get("robotwin", {}) if profile == "full_controls" else {}
    require_robotwin_dynamics(records, calibration, default_options=defaults)
    return records
