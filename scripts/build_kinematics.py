"""Build the Xbox One S viewer kinematics from pinned evidence.

This builder does not create a calibrated Xbox One S physical model. It derives
an inspectable kinematic preview from the owner-approved BatonyRobson appearance,
the source artist animation and explicitly labelled reference-component data.
Unknown dynamics remain null.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path

from asset_spec import W3C_BROWSER_CHANNEL_DEFINITIONS


ROOT = Path(__file__).resolve().parents[1]
STATIC_INVENTORY = ROOT / "assets/xbox_one_s/visual/inventory.json"
MOTION_SUMMARY = ROOT / "references/xbox_one_s_artist_animation_summary.json"
DIMENSIONS = ROOT / "references/1708_dimensions.json"
STICK_REFERENCE = ROOT / "references/stick_envelope.json"
CATALOG = ROOT / "references/catalog.json"
EVIDENCE_OUTPUT = ROOT / "build/generated/kinematics/xbox_one_s_evidence.json"
PROFILE_OUTPUT = ROOT / "build/generated/kinematics/xbox_one_s.json"
AUDIT_OUTPUT = ROOT / "build/experiments/xbox_one_s/kinematics_build_audit.json"

PROFILE_ID = "xbox_one_s"
VARIANT_ID = PROFILE_ID
EXPECTED_FULL_MOTION_AUDIT_SHA256 = "4c97d513d66f008e5cbc2b375d3c98692cfb495ecf32178c42d399304b31e6df"

PART_TO_CONTROL = {
    "Controller Body": "shell",
    "A Button": "a",
    "B Button": "b",
    "X Button": "x",
    "Y Button": "y",
    "Bumper_L": "left_shoulder",
    "Bumper_R": "right_shoulder",
    "Connect Button": "pair",
    "D-Pad": "dpad",
    "Menu_L": "view",
    "Menu_R": "menu",
    "Stick_L": "left_stick",
    "Stick_R": "right_stick",
    "Trigger_L": "left_trigger",
    "Trigger_R": "right_trigger",
    "XboxButton": "guide",
}

CONTROL_TO_BONE = {
    "a": "A Button_08",
    "b": "B Button_09",
    "x": "X Button_07",
    "y": "Y Button_010",
    "left_shoulder": "Bumper_L_04",
    "right_shoulder": "Bumper_R_03",
    "pair": "ConnectButton_05",
    "dpad": "DPad_016",
    "view": "Menu_L_013",
    "menu": "Menu_R_00",
    "left_stick": "Stick_L_015",
    "right_stick": "Stick_R_014",
    "left_trigger": "Trigger_L_012",
    "right_trigger": "Trigger_R_011",
    "guide": "XBoxButton_06",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def finite_tree(value):
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(value)
    if isinstance(value, list):
        return all(finite_tree(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and finite_tree(item) for key, item in value.items())
    return False


def scaled(vector, factor):
    return [float(value) * factor for value in vector]


def unit(vector):
    length = math.sqrt(sum(float(value) ** 2 for value in vector))
    require(length > 1e-12, "cannot normalize zero vector")
    return [float(value) / length for value in vector]


def parameter(*, value, unit_name, status, evidence, derivation, uncertainty, applicability):
    return {
        "value": value,
        "unit": unit_name,
        "status": status,
        "evidence": evidence,
        "derivation": derivation,
        "uncertainty": uncertainty,
        "harness": {
            "kind": "python_derivation",
            "path": "scripts/build_kinematics.py",
            "entrypoint": "build",
        },
        "applicability": applicability,
    }


def unknown(reason, unit_name=None):
    return {
        "value": None,
        "unit": unit_name,
        "status": "unknown",
        "evidence": [],
        "harness": "scripts/build_kinematics.py:build",
        "reason": reason,
    }


def channel_index(name):
    return next(
        index
        for index, item in enumerate(W3C_BROWSER_CHANNEL_DEFINITIONS)
        if item[0] == name
    )


def build(output: Path | None = None):
    inventory = json.loads(STATIC_INVENTORY.read_text())
    motion = json.loads(MOTION_SUMMARY.read_text())
    dimensions = json.loads(DIMENSIONS.read_text())
    stick_reference = json.loads(STICK_REFERENCE.read_text())
    catalog = json.loads(CATALOG.read_text())
    catalog_sources = catalog.get("sources")
    require(isinstance(catalog_sources, dict) and catalog_sources, "evidence catalog has no source index")
    require(motion["full_audit_sha256"] == EXPECTED_FULL_MOTION_AUDIT_SHA256, "full motion audit binding changed")
    require(motion.get("toolchain", {}).get("blender_version") == [4, 5, 9], "artist-motion audit toolchain changed")
    require(inventory["source_sha256"] == motion["source_sha256"], "visual and motion sources differ")
    require(len(inventory["objects"]) == 16, "expected exactly sixteen exported parts")
    require(set(PART_TO_CONTROL) == {item["name"] for item in inventory["objects"]}, "part mapping is incomplete")
    require(stick_reference["status"] == "reference_component_constraint_not_installed_xbox_joint", "stick reference lost its applicability warning")

    objects = {item["name"]: item for item in inventory["objects"]}
    bounds_min = [min(item["bounds_native"][0][axis] for item in objects.values()) for axis in range(3)]
    bounds_max = [max(item["bounds_native"][1][axis] for item in objects.values()) for axis in range(3)]
    extents = [bounds_max[axis] - bounds_min[axis] for axis in range(3)]
    target_extents = [
        dimensions["dimensions_m"]["width"],
        dimensions["dimensions_m"]["length"],
        dimensions["dimensions_m"]["depth_height"],
    ]
    axis_scales = [target_extents[index] / extents[index] for index in range(3)]
    metric_scale = axis_scales[0]
    estimated_extents = [extent * metric_scale for extent in extents]
    residuals = [estimated_extents[index] - target_extents[index] for index in range(3)]

    action = motion["actions"]
    require(len(action) == 1 and action[0]["name"] == "Test", "unexpected artist action layout")
    bones = {item["bone"]: item for item in action[0]["bones"]}
    require(set(CONTROL_TO_BONE.values()) <= set(bones), "motion summary is missing a mapped bone")

    non_statistical_scale_interval = [min(axis_scales), max(axis_scales)]
    parameters = {
        "metric_scale": parameter(
            value=metric_scale,
            unit_name="m/native_unit",
            status="derived",
            evidence=["microsoft_1708_dimensions", "batony_xbox_one_s_visual"],
            derivation={
                "method": "Uniformly fit the downloaded candidate's complete source-world X extent to the Microsoft-published whole-controller width; do not stretch axes independently.",
                "inputs": {
                    "native_bounds": [bounds_min, bounds_max],
                    "native_extents": extents,
                    "target_extents_m": target_extents,
                    "formula": "scale = target_width_m / native_x_extent",
                },
            },
            uncertainty={
                "type": "non_statistical_shape_mismatch_interval",
                "range": non_statistical_scale_interval,
                "unit": "m/native_unit",
                "quantity": "Range of independent X/Y/Z extent-fit scale ratios; not a manufacturing tolerance or confidence interval.",
                "confidence": None,
            },
            applicability="Estimated appearance-preview scale only. The visual candidate is not dimensionally or revision verified.",
        )
    }

    def artist_anchor_parameter(control):
        bone = bones[CONTROL_TO_BONE[control]]
        fit = bone["effective_rotation_pivot_fit"]
        uncertainty = None
        if fit is not None:
            uncertainty = {
                "type": "artist_rigid_transform_reconstruction_residual",
                "range": [
                    fit["baseline_origin_translation_fit_rms_native"] * metric_scale,
                    fit["baseline_origin_translation_fit_max_native"] * metric_scale,
                ],
                "unit": "m",
                "quantity": "RMS and maximum error when the artist baseline-pose origin reconstructs sampled relative translations via t=(I-R)p; not physical uncertainty.",
                "confidence": None,
            }
        return parameter(
            value=scaled(bone["baseline_pose_origin_world_native"], metric_scale),
            unit_name="m_in_source_world_frame",
            status="estimated",
            evidence=["batony_artist_motion_prior", "batony_xbox_one_s_visual", "microsoft_1708_dimensions"],
            derivation={
                "method": "Take the artist rig baseline-pose matrix origin in the world-baked visual frame and apply the width-derived uniform metric scale.",
                "inputs": {
                    "control": control,
                    "bone": CONTROL_TO_BONE[control],
                    "baseline_pose_origin_world_native": bone["baseline_pose_origin_world_native"],
                    "meters_per_native_unit": metric_scale,
                    "rotation_fit": fit,
                },
            },
            uncertainty=uncertainty,
            applicability=(
                "Artist-rig pivot candidate for the kinematic preview; not a measured mechanical pivot."
                if fit is not None
                else "Artist render anchor only. A pivot does not affect a pure prismatic transform; this is not a mechanical pivot claim."
            ),
        )

    for control in CONTROL_TO_BONE:
        parameters[f"{control}_artist_anchor"] = artist_anchor_parameter(control)

    def artist_translation_parameter(control):
        peak = bones[CONTROL_TO_BONE[control]]["peak_translation"]
        value = peak["magnitude_native"] * metric_scale
        return parameter(
            value=value,
            unit_name="m",
            status="estimated",
            evidence=["batony_artist_motion_prior", "batony_xbox_one_s_visual", "microsoft_1708_dimensions"],
            derivation={
                "method": "Multiply the artist animation's peak neutral-relative translation magnitude by the width-fit uniform scale.",
                "inputs": {
                    "control": control,
                    "bone": CONTROL_TO_BONE[control],
                    "peak_translation_native": peak["magnitude_native"],
                    "meters_per_native_unit": metric_scale,
                },
            },
            uncertainty={
                "type": "non_statistical_scale_only_interval",
                "range": [peak["magnitude_native"] * non_statistical_scale_interval[0], peak["magnitude_native"] * non_statistical_scale_interval[1]],
                "unit": "m",
                "quantity": "Only candidate whole-shape scale mismatch; excludes unknown artist-vs-hardware motion error.",
                "confidence": None,
            },
            applicability="Appearance-matched kinematic preview; not measured cap travel.",
        )

    translation_controls = [
        "a", "b", "x", "y", "left_shoulder", "right_shoulder",
        "view", "menu", "guide", "pair",
    ]
    for control in translation_controls:
        parameters[f"{control}_travel"] = artist_translation_parameter(control)
        direction = unit(bones[CONTROL_TO_BONE[control]]["peak_translation"]["vector_native"])
        parameters[f"{control}_motion_axis"] = parameter(
            value=direction,
            unit_name="unit_vector_in_source_world_frame",
            status="estimated",
            evidence=["batony_artist_motion_prior"],
            derivation={
                "method": "Normalize the peak neutral-relative artist translation vector.",
                "inputs": {"control": control, "bone": CONTROL_TO_BONE[control]},
            },
            uncertainty=None,
            applicability="Estimated appearance-preview translation direction only; not a measured guide axis.",
        )

    for control in ("left_trigger", "right_trigger", "dpad"):
        peak = bones[CONTROL_TO_BONE[control]]["peak_rotation"]
        parameters[f"{control}_rotation"] = parameter(
            value=peak["angle_rad"],
            unit_name="rad",
            status="estimated",
            evidence=["batony_artist_motion_prior"],
            derivation={
                "method": "Use the maximum neutral-relative artist animation rotation magnitude as a visual motion prior.",
                "inputs": {"control": control, "bone": CONTROL_TO_BONE[control], "peak_frame": peak["frame"]},
            },
            uncertainty=None,
            applicability="Estimated appearance-preview motion only; no physical uncertainty bound can be inferred from artist keyframes.",
        )

    for control in ("left_trigger", "right_trigger"):
        peak = bones[CONTROL_TO_BONE[control]]["peak_rotation"]
        parameters[f"{control}_rotation_axis"] = parameter(
            value=unit(peak["axis_world"]),
            unit_name="unit_vector_in_source_world_frame",
            status="estimated",
            evidence=["batony_artist_motion_prior"],
            derivation={
                "method": "Normalize the artist peak-rotation world axis.",
                "inputs": {"control": control, "bone": CONTROL_TO_BONE[control], "peak_frame": peak["frame"]},
            },
            uncertainty=None,
            applicability="Estimated appearance-preview hinge axis only; not a measured trigger axis.",
        )

    for control in ("left_stick", "right_stick", "dpad"):
        ranges = bones[CONTROL_TO_BONE[control]]["peak_rotation"]["observed_axis_component_ranges"]
        for semantic, value in (("horizontal", [0.0, 1.0, 0.0]), ("vertical", [1.0, 0.0, 0.0])):
            parameters[f"{control}_{semantic}_rotation_axis"] = parameter(
                value=value,
                unit_name="unit_vector_in_source_world_frame",
                status="estimated",
                evidence=["batony_artist_motion_prior"],
                derivation={
                    "method": "Use a separable source-coordinate basis for the two-axis runtime; the artist samples contain rotations aligned with both signed source X and Y axes.",
                    "inputs": {
                        "control": control,
                        "bone": CONTROL_TO_BONE[control],
                        "observed_artist_axis_component_ranges": ranges,
                        "semantic": semantic,
                    },
                },
                uncertainty=None,
                applicability="Estimated appearance-preview separable control basis; not a measured gimbal axis.",
            )

    parameters["stick_click_axis"] = parameter(
        value=[0.0, 0.0, -1.0],
        unit_name="unit_vector_in_source_world_frame",
        status="estimated",
        evidence=["batony_xbox_one_s_visual"],
        derivation={
            "method": "Use the inward negative source-Z face-normal direction for the visual click surrogate.",
            "inputs": {"source_frame": "blender_source_z_up_right_handed", "artist_click_animation": None},
        },
        uncertainty=None,
        applicability="Visual click-direction assumption only. The artist asset has no verified stick-click animation or mechanical guide axis.",
    )

    stick_limit = math.radians(float(stick_reference["half_sweep_max_deg"]))
    parameters["stick_tilt_limit"] = parameter(
        value=stick_limit,
        unit_name="rad",
        status="reference",
        evidence=["alps_stick", "batony_artist_motion_prior"],
        derivation={
            "method": "Convert the reference component's 23 degree maximum each-direction angle to radians; the right artist stick reaches the same rounded angle.",
            "inputs": {"reference_degrees": stick_reference["half_sweep_max_deg"], "component_match": None},
        },
        uncertainty=None,
        applicability="Reference component upper envelope for the kinematic preview only; installed Xbox component match is unconfirmed and the enclosure limit is unknown.",
    )
    click = catalog["reference_values"]["stick_click_travel"]
    parameters["stick_click_travel"] = parameter(
        value=click["value"],
        unit_name="m",
        status="reference",
        evidence=["alps_stick"],
        derivation={
            "method": "Adopt the unverified reference component's center-push travel for visual preview only.",
            "inputs": {"reference_value": click["value"], "reference_lower": click["lower"], "reference_upper": click["upper"]},
        },
        uncertainty={
            "type": "manufacturer_component_tolerance",
            "range": [click["lower"], click["upper"]],
            "unit": "m",
            "quantity": "Reference component travel tolerance; not an assembled Xbox tolerance.",
            "confidence": None,
        },
        applicability="Reference-component preview only; Xbox component identity is unconfirmed.",
    )

    # The runtime deliberately uses a simple circular envelope in its two joint
    # coordinates.  That is not the exact equal-inclination boundary documented
    # by the reference-component record.  For the composed orthogonal rotations,
    # cos(inclination) = cos(q_horizontal) * cos(q_vertical).  On the circular
    # boundary q_horizontal**2 + q_vertical**2 = t**2, the cardinal directions
    # reach t while the diagonal directions have the smallest inclination.
    diagonal_joint_coordinate = stick_limit / math.sqrt(2.0)
    diagonal_inclination = math.acos(math.cos(diagonal_joint_coordinate) ** 2)
    maximum_inclination_shortfall = stick_limit - diagonal_inclination
    require(maximum_inclination_shortfall >= 0.0, "joint-space stick envelope is not conservative")
    stick_envelope_approximation = {
        "status": "conservative_joint_space_approximation_not_physical_gate",
        "coordinate_boundary": "q_horizontal^2 + q_vertical^2 = reference_limit^2",
        "orientation_formula": "inclination = acos(cos(q_horizontal) * cos(q_vertical))",
        "rotation_scope": "The formula applies to the preview's composed orthogonal rotations; it does not identify the target Xbox gimbal sequence.",
        "reference_limit_rad": stick_limit,
        "inclination_range_on_joint_space_boundary_rad": [diagonal_inclination, stick_limit],
        "maximum_inclination_shortfall_rad": maximum_inclination_shortfall,
        "maximum_inclination_shortfall_deg": math.degrees(maximum_inclination_shortfall),
        "relative_shortfall_at_diagonal": maximum_inclination_shortfall / stick_limit,
        "extrema": {
            "maximum_inclination": "cardinal directions, where one coordinate is zero",
            "minimum_inclination": "diagonal directions, where |q_horizontal| = |q_vertical| = reference_limit/sqrt(2)",
        },
        "derivation": (
            "Let u=q_horizontal^2 and v=q_vertical^2 with u+v=t^2. "
            "log(cos(sqrt(u))) is concave for 0<=u<t^2<pi^2/4, so the cosine product is largest "
            "at u=v=t^2/2 and smallest at the cardinal endpoints. Because acos is decreasing, "
            "the stated inclination extrema follow analytically."
        ),
        "harness": "scripts/build_kinematics.py:build",
        "validation": {
            "path": "tests/test_kinematics.py",
            "method": "Sample 7200 uniformly spaced azimuths on the circular joint-space boundary and verify every composed-rotation inclination lies within the analytic extrema, with cardinal and diagonal samples attaining the bounds.",
            "sample_count": 7200,
            "numerical_tolerance_rad": 1e-12,
        },
        "evidence": ["alps_stick"],
        "warning": "This quantifies preview under-travel only. It is not an Xbox aperture, gate-shape or component-match claim.",
    }

    for parameter_name, record in parameters.items():
        evidence_ids = record.get("evidence")
        require(isinstance(evidence_ids, list) and evidence_ids, f"{parameter_name}: missing evidence IDs")
        missing_ids = sorted(set(evidence_ids) - set(catalog_sources))
        require(not missing_ids, f"{parameter_name}: unknown evidence IDs {missing_ids}")
    require(
        set(stick_envelope_approximation["evidence"]) <= set(catalog_sources),
        "stick-envelope approximation cites an unknown evidence ID",
    )

    channels = [
        {
            "name": name,
            "kind": kind,
            "tensor_index": tensor_index,
            "standard_index": standard_index,
            "range": list(value_range),
        }
        for name, kind, tensor_index, standard_index, value_range
        in W3C_BROWSER_CHANNEL_DEFINITIONS
    ]
    nodes = []
    for item in inventory["objects"]:
        nodes.append(
            {
                "source_node": Path(item["file"]).stem,
                "source_part": item["name"],
                "control": PART_TO_CONTROL[item["name"]],
                "joint_ids": [],
            }
        )
    node_by_control = {item["control"]: item for item in nodes}
    joints = []

    def add_joint(joint):
        require(joint["node"] in {item["source_node"] for item in nodes}, f"unknown node {joint['node']}")
        for reference in ("parameter_ref", "axis_parameter_ref", "pivot_parameter_ref"):
            require(joint.get(reference) in parameters, f"{joint['id']}: unknown {reference}")
        require(
            max(abs(actual - expected) for actual, expected in zip(joint["axis_source"], parameters[joint["axis_parameter_ref"]]["value"])) <= 1e-12,
            f"{joint['id']}: axis differs from its evidence record",
        )
        require(
            max(abs(actual - expected) for actual, expected in zip(joint["pivot_source_m"], parameters[joint["pivot_parameter_ref"]]["value"])) <= 1e-12,
            f"{joint['id']}: pivot differs from its evidence record",
        )
        joints.append(joint)
        next(item for item in nodes if item["source_node"] == joint["node"])["joint_ids"].append(joint["id"])

    def pivot(control):
        return parameters[f"{control}_artist_anchor"]["value"]

    def simple_translation(control, channel):
        record = parameters[f"{control}_travel"]
        direction = unit(bones[CONTROL_TO_BONE[control]]["peak_translation"]["vector_native"])
        add_joint({
            "id": f"{control}_press", "node": node_by_control[control]["source_node"],
            "type": "prismatic", "axis_source": direction, "pivot_source_m": pivot(control),
            "axis_parameter_ref": f"{control}_motion_axis", "pivot_parameter_ref": f"{control}_artist_anchor",
            "limits": [0.0, record["value"]], "unit": "m", "parameter_ref": f"{control}_travel",
            "driver": {"kind": "linear_channel", "channel": channel_index(channel), "signal_range": [0.0, 1.0]},
        })

    for control, channel in (
        ("a", "a"), ("b", "b"), ("x", "x"), ("y", "y"),
        ("left_shoulder", "left_shoulder"), ("right_shoulder", "right_shoulder"),
        ("view", "view"), ("menu", "menu"), ("guide", "guide"),
    ):
        simple_translation(control, channel)

    for side, control, channel in (
        ("left", "left_trigger", "left_trigger"),
        ("right", "right_trigger", "right_trigger"),
    ):
        peak = bones[CONTROL_TO_BONE[control]]["peak_rotation"]
        add_joint({
            "id": f"{side}_trigger_hinge", "node": node_by_control[control]["source_node"],
            "type": "revolute", "axis_source": unit(peak["axis_world"]), "pivot_source_m": pivot(control),
            "axis_parameter_ref": f"{control}_rotation_axis", "pivot_parameter_ref": f"{control}_artist_anchor",
            "limits": [0.0, parameters[f"{control}_rotation"]["value"]], "unit": "rad",
            "parameter_ref": f"{control}_rotation",
            "driver": {"kind": "linear_channel", "channel": channel_index(channel), "signal_range": [0.0, 1.0]},
        })

    for side, control, x_channel, y_channel, click_channel in (
        ("left", "left_stick", "lx", "ly", "left_stick_click"),
        ("right", "right_stick", "rx", "ry", "right_stick_click"),
    ):
        node = node_by_control[control]["source_node"]
        shared_pivot = pivot(control)
        for suffix, axis, channel in (
            ("x", [0.0, 1.0, 0.0], x_channel),
            ("y", [1.0, 0.0, 0.0], y_channel),
        ):
            add_joint({
                "id": f"{side}_stick_{suffix}", "node": node, "type": "revolute",
                "axis_source": axis, "pivot_source_m": shared_pivot,
                "axis_parameter_ref": f"{control}_{'horizontal' if suffix == 'x' else 'vertical'}_rotation_axis",
                "pivot_parameter_ref": f"{control}_artist_anchor",
                "limits": [-stick_limit, stick_limit], "unit": "rad", "parameter_ref": "stick_tilt_limit",
                "driver": {"kind": "linear_channel", "channel": channel_index(channel), "signal_range": [-1.0, 1.0]},
            })
        add_joint({
            "id": f"{side}_stick_click", "node": node, "type": "prismatic",
            "axis_source": [0.0, 0.0, -1.0], "pivot_source_m": shared_pivot,
            "axis_parameter_ref": "stick_click_axis", "pivot_parameter_ref": f"{control}_artist_anchor",
            "limits": [0.0, parameters["stick_click_travel"]["value"]], "unit": "m",
            "parameter_ref": "stick_click_travel",
            "driver": {"kind": "linear_channel", "channel": channel_index(click_channel), "signal_range": [0.0, 1.0]},
        })

    dpad_limit = parameters["dpad_rotation"]["value"]
    dpad_node = node_by_control["dpad"]["source_node"]
    dpad_pivot = pivot("dpad")
    add_joint({
        "id": "dpad_horizontal", "node": dpad_node, "type": "revolute",
        "axis_source": [0.0, 1.0, 0.0], "pivot_source_m": dpad_pivot,
        "axis_parameter_ref": "dpad_horizontal_rotation_axis", "pivot_parameter_ref": "dpad_artist_anchor",
        "limits": [-dpad_limit, dpad_limit], "unit": "rad", "parameter_ref": "dpad_rotation",
        "driver": {"kind": "difference_channels", "negative_channel": channel_index("dpad_left"), "positive_channel": channel_index("dpad_right")},
    })
    add_joint({
        "id": "dpad_vertical", "node": dpad_node, "type": "revolute",
        "axis_source": [1.0, 0.0, 0.0], "pivot_source_m": dpad_pivot,
        "axis_parameter_ref": "dpad_vertical_rotation_axis", "pivot_parameter_ref": "dpad_artist_anchor",
        "limits": [-dpad_limit, dpad_limit], "unit": "rad", "parameter_ref": "dpad_rotation",
        "driver": {"kind": "difference_channels", "negative_channel": channel_index("dpad_up"), "positive_channel": channel_index("dpad_down")},
    })

    pair_record = parameters["pair_travel"]
    pair_direction = unit(bones[CONTROL_TO_BONE["pair"]]["peak_translation"]["vector_native"])
    add_joint({
        "id": "pair_press", "node": node_by_control["pair"]["source_node"], "type": "prismatic",
        "axis_source": pair_direction, "pivot_source_m": pivot("pair"),
        "axis_parameter_ref": "pair_motion_axis", "pivot_parameter_ref": "pair_artist_anchor",
        "limits": [0.0, pair_record["value"]], "unit": "m", "parameter_ref": "pair_travel",
        "driver": {"kind": "physical_event", "event": "pair_bind_connect", "signal_range": [0.0, 1.0]},
    })

    constraints = [
        {
            "id": f"{side}_stick_radial_envelope", "type": "radial",
            "joint_ids": [f"{side}_stick_x", f"{side}_stick_y"],
            "radius": stick_limit, "unit": "rad", "parameter_ref": "stick_tilt_limit",
            "projection": "radial_clamp",
            "coordinate_space": "joint_coordinates",
            "model_status": "conservative_joint_space_approximation_not_physical_gate",
            "approximation_ref": "stick_joint_space_envelope",
            "loss": "Signals outside the unit disk are radially projected, so the represented state differs from the raw state.",
        }
        for side in ("left", "right")
    ]
    constraints.append({
        "id": "dpad_radial_envelope", "type": "radial",
        "joint_ids": ["dpad_horizontal", "dpad_vertical"],
        "radius": dpad_limit, "unit": "rad", "parameter_ref": "dpad_rotation",
        "projection": "radial_clamp",
        "coordinate_space": "joint_coordinates",
        "model_status": "artist_motion_joint_space_approximation_not_physical_gate",
        "approximation_ref": None,
        "loss": "Simultaneous cardinal inputs are projected to the artist-derived angular envelope; physical diagonal travel is unknown.",
    })

    driven = []
    for joint in joints:
        driver = joint["driver"]
        if driver["kind"] == "linear_channel":
            driven.append(driver["channel"])
        elif driver["kind"] == "difference_channels":
            driven.extend([driver["negative_channel"], driver["positive_channel"]])
    require(sorted(driven) == list(range(21)), f"runtime must represent exactly 21 channels, got {sorted(driven)}")

    rotating_controls = ("left_trigger", "right_trigger", "left_stick", "right_stick", "dpad")
    float32_epsilon = 2.0 ** -23
    maximum_native_coordinate = max(abs(value) for value in bounds_min + bounds_max)
    pivot_fit_roundoff_ulp_multiplier = 128
    pivot_fit_gate_native = pivot_fit_roundoff_ulp_multiplier * float32_epsilon * max(1.0, maximum_native_coordinate)
    pivot_fit_maxima = {
        control: bones[CONTROL_TO_BONE[control]]["effective_rotation_pivot_fit"]["baseline_origin_translation_fit_max_native"]
        for control in rotating_controls
    }
    require(all(value <= pivot_fit_gate_native for value in pivot_fit_maxima.values()), "artist baseline origins do not reconstruct sampled rigid transforms")

    evidence = {
        "schema_version": 1,
        "profile_id": PROFILE_ID,
        "status": "kinematic_preview_not_hardware_calibrated",
        "parameter_status": "mixed_reference_derived_estimated_and_unknown",
        "hardware_calibrated": False,
        "source_bindings": {
            "static_inventory": str(STATIC_INVENTORY.relative_to(ROOT)),
            "source_glb_sha256": inventory["source_sha256"],
            "static_glb": inventory["assembled_glb"],
            "static_glb_sha256": inventory["assembled_glb_sha256"],
            "artist_motion_summary": str(MOTION_SUMMARY.relative_to(ROOT)),
            "full_artist_motion_audit_sha256": EXPECTED_FULL_MOTION_AUDIT_SHA256,
            "full_artist_motion_audit_gpu_path": motion["full_audit_storage"],
            "dimension_evidence": str(DIMENSIONS.relative_to(ROOT)),
            "stick_reference": str(STICK_REFERENCE.relative_to(ROOT)),
            "evidence_catalog": str(CATALOG.relative_to(ROOT)),
        },
        "evidence_index": {
            "catalog": str(CATALOG.relative_to(ROOT)),
            "available_ids": sorted(catalog_sources),
        },
        "scale_fit": {
            "native_bounds": [bounds_min, bounds_max],
            "native_extents": extents,
            "target_extents_m": target_extents,
            "axis_independent_fit_scales_m_per_native_unit": axis_scales,
            "selected_uniform_scale_m_per_native_unit": metric_scale,
            "estimated_extents_m": estimated_extents,
            "residuals_m": residuals,
            "selection": "width_exact_uniform_scale",
            "warning": "Length/height residuals are retained; no non-uniform deformation is used to hide candidate shape mismatch.",
        },
        "artist_pivot_validation": {
            "method": "For every sampled rotating control, verify t=(I-R)p using the artist baseline-pose origin p.",
            "maximum_residuals_native": pivot_fit_maxima,
            "numerical_gate_native": pivot_fit_gate_native,
            "gate_derivation": {
                "formula": "128 * float32_epsilon * max(1, maximum_abs_native_coordinate)",
                "float32_epsilon": float32_epsilon,
                "maximum_abs_native_coordinate": maximum_native_coordinate,
                "ulp_multiplier": pivot_fit_roundoff_ulp_multiplier,
                "multiplier_role": "Conservative harness-only budget for imported float32 matrices, decomposition and chained arithmetic; not a physical tolerance.",
            },
            "largest_observed_fraction_of_gate": max(pivot_fit_maxima.values()) / pivot_fit_gate_native,
            "gate_semantics": "Numerical artist-rig reconstruction check only; not a physical accuracy tolerance.",
            "passed": True,
        },
        "constraint_approximations": {
            "stick_joint_space_envelope": stick_envelope_approximation,
        },
        "parameters": parameters,
        "unknown_physical_parameters": {
            name: unknown("No target-specific measurement or applicable physical source is available; the kinematic preview must not invent this value.", unit_name)
            for name, unit_name in {
                "body_and_control_masses": "kg",
                "body_and_control_inertias": "kg*m^2",
                "centers_of_mass": "m",
                "collision_geometry": None,
                "contact_friction": "1",
                "contact_restitution": "1",
                "button_activation_thresholds": "m",
                "restoring_force_and_torque_curves": "m_or_rad,N_or_N*m",
                "joint_damping": "N*s/m_or_N*m*s/rad",
                "joint_friction": "N_or_N*m",
                "real_hid_transfer_functions": "1",
            }.items()
        },
        "acceptance": {
            "appearance_binding": True,
            "target_appearance_identity_accepted": True,
            "interactive_kinematic_profile": True,
            "canonical_schema_v2_adapter": False,
            "metric_geometry_verified": False,
            "real_controller_verified": False,
            "physical_acceptance": False,
            "dynamics_ready": False,
        },
    }

    profile = {
        "schema_version": 2,
        "schema_name": "appearance_kinematics_runtime",
        "profile_id": PROFILE_ID,
        "variant_id": VARIANT_ID,
        "status": "kinematic_preview_not_physical_asset",
        "parameter_status": "mixed_reference_derived_estimated_and_unknown",
        "hardware_calibrated": False,
        "source_bindings": evidence["source_bindings"],
        "visual": {
            "mode": "gltf_container",
            "file": inventory["assembled_glb"],
            "sha256": inventory["assembled_glb_sha256"],
            "materials": "embedded",
            "meters_per_native_unit": metric_scale,
            "source_frame": "blender_source_z_up_right_handed",
            "gltf_frame": "gltf_y_up_right_handed",
            "gltf_to_viewer_rotation_x_rad": math.pi / 2,
            "source_to_gltf_vector": "[x,y,z] -> [x,z,-y]",
        },
        "channels": channels,
        "nodes": nodes,
        "joints": joints,
        "constraints": constraints,
        "physical_events": [{"name": "pair_bind_connect", "joint_id": "pair_press", "tensor_channel": None}],
        "mapping_semantics": {
            "kind": "forward_only_numeric_preview",
            "scope": "21-channel/event signals to preview joint coordinates and represented signals; mesh pose and contact are outside this mapping contract.",
            "autograd": "none_javascript_runtime_not_torch_or_jax",
            "training_warning": "This JavaScript implementation does not establish an autograd path for VLA training. A separately tested Torch/JAX adapter is required before joint-gradient claims.",
            "not_physical_hid_calibration": True,
            "digital_channels_remain_float": True,
            "smoothness": {
                "linear_channel_interior": "affine",
                "radial_projection_inside_disk_including_origin": "identity_and_smooth_in_an_open_neighborhood_of_the_origin",
                "radial_projection_outside_disk": "nonlinear_due_to_radius_division",
                "non_smooth_sets": [
                    "linear/event clamp activation boundaries",
                    "radial projection boundary where joint-coordinate norm equals radius",
                    "difference-channel saturation boundaries where positive-negative equals -1 or +1",
                    "difference-channel represented split at zero due to sign branch and max",
                ],
            },
            "inverse_policy": "return_represented_state_after_constraint_projection",
        },
        "parameter_source": "/generated/kinematics/xbox_one_s_evidence.json",
        "acceptance": evidence["acceptance"],
    }
    require(finite_tree(evidence) and finite_tree(profile), "generated documents contain non-finite values")
    audit = {
        "schema_version": 1,
        "profile_id": PROFILE_ID,
        "passed": True,
        "external_input_sha256": {
            "source_artist_glb": inventory["source_sha256"],
            "static_visual_glb": inventory["assembled_glb_sha256"],
            "full_artist_motion_audit": EXPECTED_FULL_MOTION_AUDIT_SHA256,
        },
        "checks": {
            "all_parameter_evidence_ids_resolve": all(
                set(record["evidence"]) <= set(catalog_sources) for record in parameters.values()
            ),
            "sixteen_unique_visual_nodes": len({item["source_node"] for item in nodes}) == 16,
            "exact_21_channel_coverage": sorted(driven) == list(range(21)),
            "pair_excluded_from_tensor": joints[-1]["driver"]["kind"] == "physical_event",
            "uniform_scale_only": True,
            "artist_rotation_pivots_reconstruct_translations": all(value <= pivot_fit_gate_native for value in pivot_fit_maxima.values()),
            "unknown_dynamics_remain_null": all(item["value"] is None for item in evidence["unknown_physical_parameters"].values()),
            "stick_joint_space_envelope_is_declared_approximation": (
                stick_envelope_approximation["status"]
                == "conservative_joint_space_approximation_not_physical_gate"
                and maximum_inclination_shortfall > 0.0
            ),
            "physical_acceptance_false": evidence["acceptance"]["physical_acceptance"] is False,
        },
        "counts": {"nodes": len(nodes), "joints": len(joints), "constraints": len(constraints), "channels": len(channels)},
    }
    require(all(audit["checks"].values()), f"build audit failed: {audit['checks']}")
    if output is not None:
        for name, value in (("xbox_one_s_evidence.json", evidence), ("xbox_one_s.json", profile), ("kinematics_build_audit.json", audit)):
            atomic_write(output / name, encoded(value))
    return evidence, profile, audit


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true")
    mode.add_argument("--check", action="store_true")
    args = parser.parse_args()
    values = build()
    outputs = (EVIDENCE_OUTPUT, PROFILE_OUTPUT)
    values_to_write = (values[0], values[1])
    if args.write:
        for path, value in zip(outputs, values_to_write):
            atomic_write(path, encoded(value))
        atomic_write(AUDIT_OUTPUT, encoded(values[2]))
    reported = (*outputs, *((AUDIT_OUTPUT,) if args.write else ()))
    print(json.dumps({"profile_id": PROFILE_ID, "mode": "write" if args.write else "check", "outputs": [str(path.relative_to(ROOT)) for path in reported]}))


if __name__ == "__main__":
    main()
