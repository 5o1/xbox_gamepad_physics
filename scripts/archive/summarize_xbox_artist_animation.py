"""Reduce the full Blender artist-animation audit to a small evidence record."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path


def norm(values):
    return math.sqrt(sum(float(value) ** 2 for value in values))


def normalized(values):
    length = norm(values)
    if length <= 1e-12:
        return None
    return [float(value) / length for value in values]


def cross(first, second):
    return [
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    ]


def determinant3(matrix):
    return (
        matrix[0][0] * (matrix[1][1] * matrix[2][2] - matrix[1][2] * matrix[2][1])
        - matrix[0][1] * (matrix[1][0] * matrix[2][2] - matrix[1][2] * matrix[2][0])
        + matrix[0][2] * (matrix[1][0] * matrix[2][1] - matrix[1][1] * matrix[2][0])
    )


def solve3(matrix, vector):
    augmented = [list(matrix[row]) + [float(vector[row])] for row in range(3)]
    for column in range(3):
        pivot_row = max(range(column, 3), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot_row][column]) <= 1e-12:
            raise ValueError("singular 3x3 system")
        augmented[column], augmented[pivot_row] = augmented[pivot_row], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(3):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][index] - factor * augmented[column][index]
                for index in range(4)
            ]
    return [augmented[row][3] for row in range(3)]


def effective_rotation_pivot(samples, peak_rotation, baseline_origin):
    """Fit the world-space point/axis line encoded by rigid artist transforms.

    For a rotation ``R`` about a point ``p``, the relative translation is
    ``t = (I - R) p``.  One rotation leaves the position along its axis
    unobservable.  Each sample therefore first yields the minimum-norm point
    on its compatible axis line.  Multiple non-parallel axes are intersected
    in weighted least squares; a single-axis control keeps the weighted
    minimum-norm line point and reports that rank limitation explicitly.
    """

    threshold = max(1e-7, abs(float(peak_rotation)) * 0.05)
    lines = []
    for sample in samples:
        angle = abs(float(sample["rotation_angle_rad"]))
        if angle <= threshold:
            continue
        matrix = sample.get("relative_matrix")
        if not (
            isinstance(matrix, list)
            and len(matrix) == 4
            and all(isinstance(row, list) and len(row) == 4 for row in matrix)
        ):
            raise ValueError("rotating sample is missing its 4x4 relative_matrix")
        axis = normalized(sample["rotation_axis_world"])
        if axis is None:
            raise ValueError("rotating sample has a zero rotation axis")
        translation = [float(value) for value in sample["translation_native"]]
        axis_cross_translation = cross(axis, translation)
        cotangent = 1.0 / math.tan(angle / 2.0)
        line_point = [
            0.5 * translation[index] + 0.5 * cotangent * axis_cross_translation[index]
            for index in range(3)
        ]
        lines.append(
            {
                "weight": angle * angle,
                "axis": axis,
                "point": line_point,
                "sample": sample,
            }
        )
    if not lines:
        return None

    normal = [[0.0 for _ in range(3)] for _ in range(3)]
    right = [0.0, 0.0, 0.0]
    total_weight = sum(line["weight"] for line in lines)
    for line in lines:
        axis, point, weight = line["axis"], line["point"], line["weight"]
        projection = [
            [(1.0 if row == column else 0.0) - axis[row] * axis[column] for column in range(3)]
            for row in range(3)
        ]
        for row in range(3):
            right[row] += weight * sum(projection[row][column] * point[column] for column in range(3))
            for column in range(3):
                normal[row][column] += weight * projection[row][column]

    trace = sum(normal[index][index] for index in range(3))
    rank_score = abs(determinant3(normal)) / ((trace / 3.0) ** 3) if trace > 0 else 0.0
    if rank_score > 1e-6:
        pivot = solve3(normal, right)
        solution_kind = "multi_axis_common_point"
        unobservable_axis = None
    else:
        pivot = [
            sum(line["weight"] * line["point"][index] for line in lines) / total_weight
            for index in range(3)
        ]
        reference_axis = lines[0]["axis"]
        aligned_axes = [
            axis if sum(axis[index] * reference_axis[index] for index in range(3)) >= 0 else [-value for value in axis]
            for axis in (line["axis"] for line in lines)
        ]
        unobservable_axis = normalized(
            [
                sum(line["weight"] * axis[index] for line, axis in zip(lines, aligned_axes))
                for index in range(3)
            ]
        )
        solution_kind = "single_axis_minimum_norm_line_point"

    def residuals_for(candidate):
        residuals = []
        for line in lines:
            sample = line["sample"]
            rotation = [row[:3] for row in sample["relative_matrix"][:3]]
            translation = [float(value) for value in sample["translation_native"]]
            prediction = [
                candidate[row] - sum(rotation[row][column] * candidate[column] for column in range(3))
                for row in range(3)
            ]
            residuals.append(norm([prediction[index] - translation[index] for index in range(3)]))
        return residuals

    residuals = residuals_for(pivot)
    baseline_residuals = residuals_for(baseline_origin)

    return {
        "effective_pivot_world_native": pivot,
        "solution_kind": solution_kind,
        "unobservable_axis_world": unobservable_axis,
        "sample_threshold_rad": threshold,
        "sample_count": len(lines),
        "normal_matrix_rank_score": rank_score,
        "translation_fit_rms_native": math.sqrt(sum(value * value for value in residuals) / len(residuals)),
        "translation_fit_max_native": max(residuals),
        "artist_baseline_origin_world_native": baseline_origin,
        "baseline_origin_translation_fit_rms_native": math.sqrt(
            sum(value * value for value in baseline_residuals) / len(baseline_residuals)
        ),
        "baseline_origin_translation_fit_max_native": max(baseline_residuals),
        "interpretation": "Artist rigid-transform pivot/axis-line fit only; not a measured mechanical joint.",
    }


def summarize_bone(bone):
    samples = bone["samples"]
    if not samples:
        raise ValueError(f'{bone.get("bone")}: no samples')
    translation_peak = max(samples, key=lambda sample: norm(sample["translation_native"]))
    rotation_peak = max(samples, key=lambda sample: abs(sample["rotation_angle_rad"]))
    translation_value = norm(translation_peak["translation_native"])
    rotation_value = abs(float(rotation_peak["rotation_angle_rad"]))
    rotating = [
        sample
        for sample in samples
        if abs(float(sample["rotation_angle_rad"])) > max(1e-7, rotation_value * 0.05)
    ]
    axis_ranges = None
    if rotating:
        axes = [sample["rotation_axis_world"] for sample in rotating]
        axis_ranges = [
            [min(float(axis[index]) for axis in axes), max(float(axis[index]) for axis in axes)]
            for index in range(3)
        ]
    end = samples[-1]
    baseline_matrix = bone.get("baseline_pose_matrix")
    if not (
        isinstance(baseline_matrix, list)
        and len(baseline_matrix) == 4
        and all(isinstance(row, list) and len(row) == 4 for row in baseline_matrix)
    ):
        raise ValueError(f'{bone.get("bone")}: missing 4x4 baseline_pose_matrix')
    baseline_origin = [float(baseline_matrix[index][3]) for index in range(3)]
    return {
        "bone": bone["bone"],
        "baseline_frame": bone["baseline_frame"],
        "rest_head_world_native": bone["rest_head_world_native"],
        "rest_tail_world_native": bone["rest_tail_world_native"],
        "baseline_pose_origin_world_native": baseline_origin,
        "peak_translation": {
            "frame": translation_peak["frame"],
            "vector_native": translation_peak["translation_native"],
            "magnitude_native": translation_value,
            "direction_world": normalized(translation_peak["translation_native"]),
        },
        "peak_rotation": {
            "frame": rotation_peak["frame"],
            "angle_rad": rotation_value,
            "axis_world": rotation_peak["rotation_axis_world"],
            "observed_axis_component_ranges": axis_ranges,
        },
        "effective_rotation_pivot_fit": effective_rotation_pivot(samples, rotation_value, baseline_origin),
        "end_frame_residual": {
            "frame": end["frame"],
            "translation_native": norm(end["translation_native"]),
            "rotation_rad": abs(float(end["rotation_angle_rad"])),
        },
    }


def summarize(report_bytes):
    report = json.loads(report_bytes)
    if report.get("status") != "artist_animation_audit_not_physical_calibration":
        raise ValueError("input is not an artist-animation audit")
    toolchain = report.get("toolchain")
    if not isinstance(toolchain, dict) or not isinstance(toolchain.get("blender_version"), list):
        raise ValueError("input is missing its Blender toolchain identity")
    actions = []
    for action in report.get("actions", []):
        actions.append(
            {
                "name": action["name"],
                "frame_range": action["frame_range"],
                "keyframe_count": len(action["keyframes"]),
                "bones": [summarize_bone(bone) for bone in action["animated_bones"]],
            }
        )
    if not actions:
        raise ValueError("input contains no actions")
    return {
        "schema_version": 1,
        "status": "artist_motion_prior_not_physical_calibration",
        "source": report["source"],
        "source_sha256": report["source_sha256"],
        "full_audit_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "full_audit_storage": "GPU node; path supplied by the calling harness",
        "coordinate_unit": report["coordinate_unit"],
        "time_unit": report["time_unit"],
        "toolchain": toolchain,
        "actions": actions,
        "adoption_policy": {
            "allowed": "Use as an explicitly labelled appearance-matched v0 motion prior or to identify which source parts move.",
            "forbidden": "Do not claim these values are measured Xbox 1708 pivots, travel, timing, force or dynamics.",
            "metric_conversion": "Requires a separately evidenced uniform-scale derivation; this report does not assign metres.",
        },
        "harness_checks": {
            "input_status_checked": True,
            "full_report_hash_recorded": True,
            "toolchain_identity_recorded": True,
            "all_actions_nonempty": True,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--full-audit-storage", required=True)
    args = parser.parse_args()
    result = summarize(args.input.read_bytes())
    result["full_audit_storage"] = args.full_audit_storage
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(f"ARTIST_ANIMATION_SUMMARY_OK actions={len(result['actions'])} output={args.output}")


if __name__ == "__main__":
    main()
