"""Engine-neutral physical derivation preserving the reviewed numerical model."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Mapping

from .calibration import CalibrationOverride, ResolvedCalibration, resolve_calibration
from .model import Evidence, Parameter


@dataclass(frozen=True)
class LinkPhysical:
    name: str
    mass_kg: Parameter
    com_m: Parameter
    inertia_com_kg_m2: Parameter
    frame: str
    principal_inertia_kg_m2: Parameter
    principal_to_link_wxyz: Parameter


@dataclass(frozen=True)
class ReturnLaw:
    initial_position: Parameter
    rest_position: Parameter
    stiffness: Parameter
    drive_damping: Parameter
    passive_damping: Parameter
    neutral_target: Parameter
    effort_limit: Parameter
    velocity_limit: Parameter
    effective_mass_or_inertia: Parameter
    damping_ratio: Parameter
    dry_friction_effort: Parameter
    armature: Parameter
    saturation_scope: str = "drive"
    realization: str = "force_limited_drive_plus_passive_damper"


@dataclass(frozen=True)
class ContactPhysical:
    material_id: str
    static_friction: Parameter
    dynamic_friction: Parameter
    restitution: Parameter
    rolling_resistance_length: Parameter
    torsional_resistance_length: Parameter


@dataclass(frozen=True)
class PhysicalDescription:
    profile: str
    motion_revision: str
    links: tuple[LinkPhysical, ...]
    return_laws: Mapping[str, ReturnLaw]
    contact_materials: tuple[ContactPhysical, ...]
    configuration_id: str


@dataclass(frozen=True)
class MassGeometry:
    """Local centroidal properties derived from closed collision meshbase solids."""
    links: Mapping[str, Mapping[str, object]]
    dynamics: Mapping[str, Mapping[str, object]]
    source: Mapping[str, object]
    left_stick_source: Mapping[str, object]
    profile: str = "full_controls"


@dataclass(frozen=True)
class ReturnForce:
    drive: float | None
    passive: float | None
    total: float | None
    dry_friction: float | None = None
    missing_reason: str = "Dry friction and load-dependent solver terms are not modeled."


def critical_damping(stiffness: float, effective_mass: float, ratio: float) -> float:
    return 2.0 * ratio * math.sqrt(stiffness * effective_mass)


def derive_joint_dynamics(profile: str, joints: Mapping[str, dict], source: dict,
                          left_stick_source: dict | None = None,
                          calibration: ResolvedCalibration | None = None) -> dict:
    """Derive neutral return laws; retain legacy backend mapping only in output adapters."""
    if profile == "left_stick":
        dynamics = source["passive_dynamics"]
        result = {name: {**record,
            "effort": float(dynamics["drive_force_limit_nm"]),
            "velocity": float(dynamics["velocity_limit_rad_s"]),
            "stiffness": dynamics["linear_equivalent_stiffness_nm_per_rad"],
            "drive_damping": dynamics["damping_nms_per_rad"],
            "passive_damping": float(dynamics["damping_nms_per_rad"]),
            "target": 0.0,
            "effective_mass_or_inertia": 0.8e-6, "damping_ratio": None,
        } for name, record in joints.items()}
        return _apply_joint_calibration(result, calibration)
    if profile != "full_controls" or left_stick_source is None:
        raise ValueError(f"unsupported physical profile: {profile}")
    left_stick = left_stick_source
    face = set(source["control_groups"]["face_buttons"]["joints"])
    small = set(source["control_groups"]["small_buttons"]["joints"])
    shoulders = set(source["control_groups"]["shoulders"]["joints"])
    triggers = set(source["control_groups"]["triggers"]["joints"])
    dpad = set(source["control_groups"]["dpad"]["joints"])
    stick_tilts = {
        "left_stick_x", "left_stick_y", "right_stick_x", "right_stick_y"
    }
    stick_clicks = {"left_stick_click", "right_stick_click"}
    one_sided = face | small | shoulders | triggers | stick_clicks
    preload_fraction = float(
        source["passive_preload_policy"]["preload_fraction"]
    )

    joints = {name: dict(record) for name, record in joints.items()}
    dynamics = {}
    for name, joint in joints.items():
        travel = float(joint["limits"][1] - joint["limits"][0])
        if name in face:
            force = float(source["control_groups"]["face_buttons"]["reference_force_n"])
            stiffness, effort, velocity, effective = force / travel, 2 * force, 1.0, 0.001
        elif name in small:
            force = float(source["control_groups"]["small_buttons"]["reference_force_n"])
            stiffness, effort, velocity, effective = force / travel, 2 * force, 1.0, 0.0005
        elif name in shoulders:
            force = float(source["control_groups"]["shoulders"]["reference_force_n"])
            stiffness, effort, velocity, effective = force / travel, 2 * force, 1.0, 0.003
        elif name in triggers:
            torque = float(source["control_groups"]["triggers"]["endpoint_torque_nm"])
            stiffness, effort, velocity, effective = torque / travel, 0.024, 10.0, 1e-6
        elif name in stick_tilts:
            record = left_stick["passive_dynamics"]
            stiffness = float(record["linear_equivalent_stiffness_nm_per_rad"])
            effort = float(record["drive_force_limit_nm"])
            velocity = float(record["velocity_limit_rad_s"])
            effective = 0.8e-6
        elif name in stick_clicks:
            group = source["control_groups"]["sticks"]
            stiffness = float(group["click_stiffness_n_per_m"])
            effort = float(group["click_force_limit_n"])
            velocity, effective = 0.2, 0.004
        elif name in dpad:
            group = source["control_groups"]["dpad"]
            stiffness = float(group["stiffness_nm_per_rad"])
            effort = float(group["force_limit_nm"])
            velocity, effective = 10.0, 1e-6
        else:
            raise ValueError(f"joint {name!r} has no dynamics policy")
        ratio = 0.7
        damping = critical_damping(stiffness, effective, ratio)
        joint.update(
            effort=effort,
            velocity=velocity,
            stiffness=stiffness,
            drive_damping=damping,
            passive_damping=damping * 0.05,
            target=(-preload_fraction * travel if name in one_sided else 0.0),
        )
        joint["effective_mass_or_inertia"] = effective
        joint["damping_ratio"] = ratio
        dynamics[name] = joint

    return _apply_joint_calibration(dynamics, calibration)


def _apply_joint_calibration(records: dict, calibration: ResolvedCalibration | None) -> dict:
    if calibration is None:
        return records
    mapping = {"stiffness": "stiffness", "drive_damping": "drive_damping", "passive_damping": "passive_damping", "effort_limit": "effort", "neutral_target": "target"}
    for path, parameter in calibration.physical.items():
        parts = path.split(".")
        if len(parts) != 3 or parts[0] != "joints":
            continue
        _, name, key = parts
        if name not in records:
            raise ValueError(f"{path}: unknown joint")
        record = records[name]
        unit = record.get("unit", "rad")
        expected = {"stiffness": "N/m" if unit == "m" else "N*m/rad", "endpoint_force": "N" if unit == "m" else "N*m", "drive_damping": "N*s/m" if unit == "m" else "N*m*s/rad", "passive_damping": "N*s/m" if unit == "m" else "N*m*s/rad", "effort_limit": "N" if unit == "m" else "N*m", "neutral_target": unit, "dry_friction_effort": "N" if unit == "m" else "N*m", "preload_fraction": "1"}[key]
        if parameter.unit != expected:
            raise ValueError(f"{path}: expected unit {expected}")
        if key in mapping:
            record[mapping[key]] = parameter.value
        elif key == "endpoint_force":
            travel = record["limits"][1] - record["limits"][0]
            record["stiffness"] = None if parameter.value is None else parameter.value / travel
        elif key == "preload_fraction":
            travel = record["limits"][1] - record["limits"][0]
            record["target"] = None if parameter.value is None else -parameter.value * travel
        elif key == "dry_friction_effort":
            record["dry_friction_effort"] = parameter.value
    return records


def derive_component_mass(component: str, properties, source: dict) -> dict:
    """Scale a local unit-density centroidal tensor by the clamped final mass."""
    import numpy as np
    policy = source["mass_policy"]
    group = ("sticks" if "stick" in component else "triggers" if "trigger" in component
             else "bumpers" if "shoulder" in component else "dpad" if component == "dpad" else "buttons")
    if properties.volume <= 0:
        raise ValueError(f"{component}: meshbase volume must be positive")
    raw_mass = properties.volume * float(policy["polymer_density_kg_m3"]) * float(policy["solid_fill_factors"][group])
    mass = max(float(policy["minimum_moving_mass_kg"]), raw_mass)
    tensor = np.asarray(properties.inertia) * (mass / properties.mass)
    return {"volume_m3": properties.volume, "unclamped_mass_kg": raw_mass,
            "mass_kg": mass, "com_m": properties.center_mass.tolist(), "inertia_kg_m2": tensor.tolist()}


def link_transforms(motion: dict) -> dict:
    """Compose the complete neutral motion chain, including local rotations."""
    import numpy as np
    import trimesh
    transforms = {"controller_body": np.eye(4)}
    pending = list(motion["joints"])
    while pending:
        ready = [joint for joint in pending if joint["parent"] in transforms]
        if not ready:
            raise ValueError("motion joint chain is disconnected")
        for joint in ready:
            transform = (trimesh.transformations.quaternion_matrix(joint["origin_orientation_wxyz"])
                         if "origin_orientation_wxyz" in joint else
                         trimesh.transformations.euler_matrix(*joint.get("rpy", (0, 0, 0)), axes="sxyz"))
            transform[:3, 3] = joint["origin"]
            transforms[joint["child"]] = transforms[joint["parent"]] @ transform
            pending.remove(joint)
    return transforms


def mass_mesh(component: str, transform, meshbase: Path):
    """Load the closed collision solid and union the two-shell stick before integration."""
    import numpy as np
    import trimesh
    from ...builders.common_collision import shell_meshes
    shells = shell_meshes(meshbase / "meshes" / f"{component}.obj")
    if len(shells) == 2:
        import manifold3d
        solids = [manifold3d.Manifold(manifold3d.Mesh64(
            np.asarray(mesh.vertices), np.asarray(mesh.faces, dtype=np.uint64))) for mesh in shells]
        union = solids[0] + solids[1]
        if union.status() != manifold3d.Error.NoError:
            raise ValueError(f"{component}: manifold union failed: {union.status()}")
        result = union.to_mesh64()
        mesh = trimesh.Trimesh(result.vert_properties[:, :3], result.tri_verts, process=False)
    else:
        mesh = shells[0]
    mesh.apply_transform(transform)
    return mesh


def principal_inertia(tensor) -> tuple:
    """Sort principal moments; anchor signs to largest components, then ensure RH axes."""
    import numpy as np
    value = np.asarray(tensor, dtype=float)
    if value.shape != (3, 3) or not np.isfinite(value).all() or not np.allclose(value, value.T, atol=1e-18):
        raise ValueError("inertia must be a finite symmetric 3x3 tensor")
    moments, axes = np.linalg.eigh(value)
    if moments.min() <= 0:
        raise ValueError("inertia must be positive definite")
    # Equal eigenvalues admit multiple valid bases; identity is deterministic for isotropy.
    if np.array_equal(value, np.eye(3) * value[0, 0]):
        axes = np.eye(3)
    for column in range(3):
        if axes[np.argmax(np.abs(axes[:, column])), column] < 0:
            axes[:, column] *= -1
    if np.linalg.det(axes) < 0:
        axes[:, -1] *= -1
    # Matrix-to-quaternion conversion; select the largest component for stability.
    candidates = np.array([1 + np.trace(axes), 1 + axes[0, 0] - axes[1, 1] - axes[2, 2],
                           1 - axes[0, 0] + axes[1, 1] - axes[2, 2], 1 - axes[0, 0] - axes[1, 1] + axes[2, 2]])
    index = int(np.argmax(candidates))
    root = math.sqrt(max(0.0, candidates[index])) * 0.5
    scale = 0.25 / root
    if index == 0:
        quat = np.array([root, (axes[2, 1] - axes[1, 2]) * scale, (axes[0, 2] - axes[2, 0]) * scale, (axes[1, 0] - axes[0, 1]) * scale])
    elif index == 1:
        quat = np.array([(axes[2, 1] - axes[1, 2]) * scale, root, (axes[0, 1] + axes[1, 0]) * scale, (axes[0, 2] + axes[2, 0]) * scale])
    elif index == 2:
        quat = np.array([(axes[0, 2] - axes[2, 0]) * scale, (axes[0, 1] + axes[1, 0]) * scale, root, (axes[1, 2] + axes[2, 1]) * scale])
    else:
        quat = np.array([(axes[1, 0] - axes[0, 1]) * scale, (axes[0, 2] + axes[2, 0]) * scale, (axes[1, 2] + axes[2, 1]) * scale, root])
    if quat[np.argmax(np.abs(quat))] < 0:
        quat *= -1
    return tuple(moments.tolist()), tuple(quat.tolist())


def _parameter(value, unit: str, locator: str, *, source: str = "references/full_controls.json", category: str = "simulation_estimate", derivation: str = "Preserve the reviewed reference value or legacy builder derivation.") -> Parameter:
    return Parameter(value, unit, (Evidence(source, locator,
        "Xbox One S simulation estimate; not an identified hardware parameter.", derivation,
        ("Uncalibrated geometry/material and numerical model assumptions remain applicable.",), category),))


def _unknown(unit: str, reason: str) -> Parameter:
    return Parameter(None, unit, (), reason)


def derive_physical(motion, geometry: MassGeometry, calibration: ResolvedCalibration) -> PhysicalDescription:
    """Wrap explicit derived values with SI units, applicability and provenance."""
    import numpy as np
    source_name = f"references/{geometry.profile}.json"
    links = []
    for name, record in geometry.links.items():
        tensor = np.asarray(record["inertia_kg_m2"], dtype=float)
        if tensor.shape == (3,):
            tensor = np.diag(tensor)
        moments, orientation = principal_inertia(tensor)
        def evidence(value, unit, field):
            reference = source_name
            category = "simulation_estimate"
            derivation = "Closed local collision solid centroid/inertia, scaled by max(minimum mass, volume*density*fill); preserve complete tensor."
            locator = "mass_policy"
            if geometry.profile == "left_stick":
                prefix = {"controller_body": "body", "left_stick_x_frame": "gimbal", "left_stick": "stick"}[name]
                suffix = {"mass": "link_mass_kg", "inertia": "inertia_kg_m2", "com": "com_m_from_pivot"}.get(field, "inertia_kg_m2")
                locator = f"mass_properties.{prefix}_{suffix}"
                derivation = geometry.source["mass_properties"]["derivation"]
            if name == "controller_body" and field == "com" or name.endswith("_frame"):
                reference = f"builders/build_robotwin_{geometry.profile}.py@7c79b29"
                locator = "build: body COM" if name == "controller_body" else "build: intermediate-frame mass/COM/inertia"
                category = "legacy_numerical_assumption"
                derivation = "Preserve the historical explicitly authored numerical regularization or COM estimate."
            elif name == "controller_body" and field in {"inertia", "principal_inertia", "principal_orientation"}:
                reference, locator = "references/left_stick.json", "mass_properties.body_inertia_kg_m2"
                derivation = "Preserve the reviewed body inertia estimate; principal moments/axes are a lossless decomposition."
            elif name == "controller_body" and field == "mass" and geometry.profile == "full_controls":
                locator = "mass_policy.whole_controller_mass_kg"
                derivation = "Subtract all moving/component and explicit intermediate-frame masses from whole-controller mass."
            if field in {"principal_inertia", "principal_orientation"}:
                derivation += " Principal axes use ascending eigh moments, largest-component-positive signs and right-handed correction; repeated eigenspaces use numpy.linalg.eigh basis."
            return _parameter(value, unit, locator, source=reference, category=category, derivation=derivation)
        links.append(LinkPhysical(name, evidence(record["mass_kg"], "kg", "mass"),
            evidence(record["com_m"], "m", "com"), evidence(tensor.tolist(), "kg*m^2", "inertia"), name,
            evidence(moments, "kg*m^2", "principal_inertia"), evidence(orientation, "1", "principal_orientation")))
    dynamics = _apply_joint_calibration({key: dict(value) for key, value in geometry.dynamics.items()}, calibration)
    laws = {}
    for name, record in dynamics.items():
        unit = record.get("unit", "rad")
        linear = unit == "m"
        units = {"stiffness": "N/m" if linear else "N*m/rad", "drive_damping": "N*s/m" if linear else "N*m*s/rad", "passive_damping": "N*s/m" if linear else "N*m*s/rad", "effort_limit": "N" if linear else "N*m", "velocity_limit": "m/s" if linear else "rad/s", "effective_mass_or_inertia": "kg" if linear else "kg*m^2"}
        def parameter(field, value, field_unit):
            override = calibration.physical.get(f"joints.{name}.{field}")
            if field == "stiffness" and f"joints.{name}.endpoint_force" in calibration.physical:
                endpoint = calibration.physical[f"joints.{name}.endpoint_force"]
                return Parameter(value, field_unit, tuple(Evidence(item.source, item.locator, item.applicability,
                    item.derivation + "; divide endpoint force/torque by the unchanged motion-contract travel.", item.assumptions,
                    item.category, item.uncertainty, item.uncertainty_reason) for item in endpoint.evidence), endpoint.missing_reason)
            if field == "neutral_target" and f"joints.{name}.preload_fraction" in calibration.physical:
                preload = calibration.physical[f"joints.{name}.preload_fraction"]
                return Parameter(value, field_unit, tuple(Evidence(item.source, item.locator, item.applicability,
                    item.derivation + "; target=-fraction*unchanged motion-contract travel.", item.assumptions,
                    item.category, item.uncertainty, item.uncertainty_reason) for item in preload.evidence), preload.missing_reason)
            if override is not None:
                return override
            if value is None:
                return _unknown(field_unit, "No explicit applicable value is available.")
            reference = source_name
            category = "simulation_estimate"
            if geometry.profile == "left_stick":
                locator = "passive_dynamics." + {"stiffness": "linear_equivalent_stiffness_nm_per_rad", "drive_damping": "damping_nms_per_rad", "passive_damping": "damping_nms_per_rad", "effort_limit": "drive_force_limit_nm", "velocity_limit": "velocity_limit_rad_s"}.get(field, "damping_method")
                derivation = "Preserve the reviewed explicit left-stick return value; passive URDF damping and drive damping remain separate."
            else:
                groups = geometry.source["control_groups"]
                group = next((key for key, group in groups.items() if name in group.get("joints", ())), "sticks")
                field_name = {"face_buttons": "reference_force_n", "small_buttons": "reference_force_n", "shoulders": "reference_force_n", "triggers": "endpoint_torque_nm", "dpad": "stiffness_nm_per_rad", "sticks": "click_stiffness_n_per_m"}[group]
                locator = f"control_groups.{group}.{field_name}"
                derivation = "Endpoint force/torque divided by motion-contract travel, or the explicit reference stiffness; preserve legacy arithmetic."
                if group == "sticks" and name.endswith(("_x", "_y")):
                    reference, locator = "references/left_stick.json", "passive_dynamics.linear_equivalent_stiffness_nm_per_rad"
                if field == "neutral_target":
                    reference, locator = source_name, "passive_preload_policy.preload_fraction"
                    derivation = "-preload_fraction*travel for one-sided joints; zero for bidirectional joints."
                elif field != "stiffness":
                    reference = "builders/build_robotwin_full_controls.py@7c79b29"
                    locator = "build: joint dynamics policy; _critical_damping"
                    category = "legacy_numerical_assumption"
                    derivation = "D_drive=2*.7*sqrt(k*effective); D_passive=.05*D_drive; effort, velocity and effective values preserve the explicit old policy."
            if field in {"initial_position", "rest_position", "effective_mass_or_inertia", "damping_ratio"}:
                reference = f"builders/build_robotwin_{geometry.profile}.py@7c79b29"
                locator = "build: joint initialization and numerical damping assumptions"
                category = "legacy_numerical_assumption"
            parameter_value = _parameter(value, field_unit, locator, source=reference, category=category, derivation=derivation)
            interval = None
            if reference == "references/left_stick.json" and field == "stiffness":
                interval = geometry.left_stick_source["passive_dynamics"]["stiffness_range_nm_per_rad"]
            if interval is not None:
                item = parameter_value.evidence[0]
                parameter_value = Parameter(value, field_unit, (Evidence(item.source, item.locator, item.applicability, item.derivation, item.assumptions, item.category, {"kind": "sensitivity_range", "bounds": interval}, None),))
            return parameter_value
        laws[name] = ReturnLaw(parameter("initial_position", 0.0, unit), parameter("rest_position", 0.0, unit),
            parameter("stiffness", record["stiffness"], units["stiffness"]),
            parameter("drive_damping", record["drive_damping"], units["drive_damping"]),
            parameter("passive_damping", record["passive_damping"], units["passive_damping"]),
            parameter("neutral_target", record["target"], unit),
            parameter("effort_limit", record["effort"], units["effort_limit"]),
            parameter("velocity_limit", record["velocity"], units["velocity_limit"]),
            parameter("effective_mass_or_inertia", record.get("effective_mass_or_inertia"), units["effective_mass_or_inertia"]),
            parameter("damping_ratio", record.get("damping_ratio"), "1"),
            calibration.physical.get(f"joints.{name}.dry_friction_effort", _unknown("N" if linear else "N*m", "No applicable generalized dry-friction measurement; the legacy PhysX coefficient is backend-specific.")),
            _unknown("kg" if linear else "kg*m^2", "No applicable armature identification is available."))
    contact = geometry.left_stick_source["contact_material"]
    def material(key):
        override = calibration.physical.get(f"contact_materials.controller.{key}")
        if override is not None:
            return override
        return Parameter(contact[key], "1", (Evidence("references/left_stick.json", f"contact_material.{key}",
            "Simulation material pair estimate pending fingertip identification.", "Explicit simulation assumption; sensitivity interval is not a measured confidence interval.",
            category="simulation_estimate", uncertainty={"kind": "sensitivity_range", "bounds": contact["sensitivity_ranges"][key]}, uncertainty_reason=None),))
    contacts = (ContactPhysical("controller", material("static_friction"), material("dynamic_friction"), material("restitution"),
        calibration.physical.get("contact_materials.controller.rolling_resistance_length", _unknown("m", "No rolling resistance evidence.")),
        calibration.physical.get("contact_materials.controller.torsional_resistance_length", _unknown("m", "No torsional resistance evidence."))),)
    return PhysicalDescription(geometry.profile, calibration.motion_revision, tuple(links), laws, contacts, calibration.configuration_id)


def evaluate_generalized_force(law: ReturnLaw, q: float, qdot: float, *, target: float | None = None) -> ReturnForce:
    """Reference drive clipping precedes the separately applied passive damper."""
    if law.saturation_scope != "drive":
        raise ValueError("only the reviewed drive saturation law is implemented")
    selected = law.neutral_target.value if target is None else target
    values = (law.stiffness.value, law.drive_damping.value, law.effort_limit.value, selected)
    drive = None if any(value is None for value in values) else max(-values[2], min(values[2], values[0] * (selected - q) - values[1] * qdot))
    passive = None if law.passive_damping.value is None else -law.passive_damping.value * qdot
    return ReturnForce(drive, passive, None if drive is None or passive is None else drive + passive)


def load_physical(profile: str = "full_controls", *, resource_directory: Path | None = None) -> PhysicalDescription:
    from ...resources import load_json_resource
    raw = json.loads((resource_directory / f"{profile}.json").read_text()) if resource_directory is not None else load_json_resource("common", "xbox_one_s", "physical", f"{profile}.json")
    def parameters(record):
        return {key: Parameter.from_dict(value) if isinstance(value, dict) and "unit" in value else value for key, value in record.items()}
    return PhysicalDescription(raw["profile"], raw["motion_revision"], tuple(LinkPhysical(**parameters(item)) for item in raw["links"]),
        {name: ReturnLaw(**parameters(item)) for name, item in raw["return_laws"].items()}, tuple(ContactPhysical(**parameters(item)) for item in raw["contact_materials"]), raw["configuration_id"])


def left_stick_links(source: dict) -> dict:
    """Keep the reviewed vertical-slice masses, COM and inertia unchanged."""
    mass = source["mass_properties"]
    return {
        "controller_body": {"mass_kg": mass["body_link_mass_kg"], "com_m": [-0.00014, -0.00325, -0.00475], "inertia_kg_m2": mass["body_inertia_kg_m2"], "legacy": True},
        "left_stick_x_frame": {"mass_kg": mass["gimbal_link_mass_kg"], "com_m": [0.0, 0.0, 0.0], "inertia_kg_m2": mass["gimbal_inertia_kg_m2"], "legacy": True},
        "left_stick": {"mass_kg": mass["stick_link_mass_kg"], "com_m": mass["stick_com_m_from_pivot"], "inertia_kg_m2": mass["stick_inertia_kg_m2"]},
    }



def build(output: Path, *, full_controls_source: Path | None = None, left_stick_source: Path | None = None,
          common_motion: Path | None = None, kinematics: Path | None = None,
          meshbase: Path | None = None, collision_root: Path | None = None,
          calibration: ResolvedCalibration | None = None) -> None:
    """Build small engine-neutral physical/provenance sidecars for both profiles."""
    import numpy as np
    from ...builders.paths import DATA_ROOT, ROOT
    from ...builders.build_kinematics import build as build_kinematics
    read = lambda path: json.loads(Path(path).read_text(encoding="utf-8"))
    source = read(full_controls_source or DATA_ROOT / "references/full_controls.json")
    left = read(left_stick_source or DATA_ROOT / "references/left_stick.json")
    motion = read(common_motion or ROOT / "build/resources/common/xbox_one_s/motion/full_controls.json")
    profile = read(kinematics) if kinematics is not None else build_kinematics()[1]
    meshbase = meshbase or ROOT / "assets/xbox_one_s/collision_meshbase"
    collision = read((collision_root or ROOT / "build/resources/common/xbox_one_s/collision") / "manifest.json")
    joints = {record["id"]: dict(record) for record in profile["joints"]}
    for common in motion["joints"]:
        joints[common["name"]].update(type=common["type"], axis_source=common["axis"], limits=[common["lower"], common["upper"]], unit=common["unit"])
    dynamics = derive_joint_dynamics("full_controls", joints, source, left)
    transforms = link_transforms(motion)
    motion_joints = {item["name"]: item for item in motion["joints"]}
    final_link = {node["control"]: motion_joints[node["joint_ids"][-1]]["child"] for node in profile["nodes"] if node["control"] != "shell"}
    links = {}
    for component in collision["components"]:
        if component in {"shell", "shell_front_plate"}:
            continue
        name = final_link[component]
        properties = mass_mesh(component, np.linalg.inv(transforms[name]), Path(meshbase)).mass_properties
        links[name] = derive_component_mass(component, properties, source)
    for name in transforms:
        if name != "controller_body" and name not in links:
            links[name] = frame_mass_properties()
    body = body_mass_properties(source, left, {name: record["mass_kg"] for name, record in links.items()})
    links = {"controller_body": body, **links}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    for name, inputs in (("full_controls", MassGeometry(links, dynamics, source, left)),
                         ("left_stick", MassGeometry(left_stick_links(left), derive_joint_dynamics("left_stick", {key: value for key, value in joints.items() if key in {"left_stick_x", "left_stick_y"}}, left), left, left, "left_stick"))):
        resolved = calibration if calibration is not None and calibration.profile == name else resolve_calibration(override=CalibrationOverride(profile=name), profile=name)
        description = derive_physical(motion, inputs, resolved)
        (output / f"{name}.json").write_text(json.dumps(asdict(description), indent=2) + "\n", encoding="utf-8")
        from .calibration import export_resolved
        export_resolved(resolved, output / f"{name}.calibration.json")


def frame_mass_properties() -> dict:
    """Explicit legacy frame regularization, never an inferred hardware measurement."""
    return {"mass_kg": 0.0005, "com_m": [0.0, 0.0, 0.0],
            "inertia_kg_m2": [[2e-8, 0.0, 0.0], [0.0, 2e-8, 0.0], [0.0, 0.0, 2e-8]], "legacy": True}


def body_mass_properties(source: dict, left_stick_source: dict, moving_mass: Mapping[str, float]) -> dict:
    body_mass = float(source["mass_policy"]["whole_controller_mass_kg"]) - sum(moving_mass.values())
    if body_mass <= 0:
        raise ValueError("moving mass estimates exceed whole controller mass")
    return {"mass_kg": body_mass, "com_m": [-0.00014, -0.00325, -0.00475],
            "inertia_kg_m2": left_stick_source["mass_properties"]["body_inertia_kg_m2"], "legacy": True}
