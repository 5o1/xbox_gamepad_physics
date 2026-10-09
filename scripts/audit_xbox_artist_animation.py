"""Audit the BatonyRobson artist animation without treating it as mechanics.

Run with Blender, for example::

    blender --background --python scripts/audit_xbox_artist_animation.py -- SOURCE.glb OUT.json

The report is intentionally expressed in source-native coordinates.  It records
what the downloaded rig does, including all action keyframes and sampled bone
transforms, but it does not promote an artist pivot, travel or timing to an Xbox
mechanical parameter.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_RECORD = PROJECT_ROOT / "references" / "xbox_one_s_material_validation.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def finite_vector(values) -> list[float]:
    result = [float(value) for value in values]
    require(all(math.isfinite(value) for value in result), "non-finite transform value")
    return result


def matrix_rows(matrix) -> list[list[float]]:
    return [finite_vector(row) for row in matrix]


def main() -> None:
    arguments = sys.argv[sys.argv.index("--") + 1 :]
    require(len(arguments) == 2, "expected SOURCE.glb OUT.json after --")
    source, output = map(Path, arguments)
    record = json.loads(SOURCE_RECORD.read_text(encoding="utf-8"))
    expected_hash = record.get("source_glb_sha256")
    require(isinstance(expected_hash, str) and len(expected_hash) == 64, "missing pinned GLB hash")
    actual_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    require(actual_hash == expected_hash, f"source SHA-256 {actual_hash} != {expected_hash}")

    import bpy

    expected_blender = record.get("animation_audit_toolchain", {}).get("blender_version")
    require(
        isinstance(expected_blender, list)
        and len(expected_blender) == 3
        and all(isinstance(value, int) for value in expected_blender),
        "missing pinned Blender version",
    )
    actual_blender = list(bpy.app.version)
    require(actual_blender == expected_blender, f"Blender version {actual_blender} != {expected_blender}")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(source))
    scene = bpy.context.scene
    armatures = [obj for obj in scene.objects if obj.type == "ARMATURE"]
    require(len(armatures) == 1, f"expected one armature, found {len(armatures)}")
    armature = armatures[0]
    if armature.animation_data is None:
        armature.animation_data_create()
    # Imported NLA tracks can otherwise combine an action with the action being
    # audited.  Muting them affects this in-memory inspection only.
    for track in armature.animation_data.nla_tracks:
        track.mute = True

    actions = sorted(bpy.data.actions, key=lambda action: action.name)
    require(actions, "source has no animation actions")
    action_reports = []
    for action in actions:
        armature.animation_data.action = action
        keyframes = sorted(
            {
                float(point.co.x)
                for curve in action.fcurves
                for point in curve.keyframe_points
            }
        )
        require(keyframes, f"{action.name}: action has no keyframes")
        first = int(math.floor(min(keyframes)))
        last = int(math.ceil(max(keyframes)))
        frames = sorted(set(keyframes) | set(range(first, last + 1)))
        animated_paths = sorted({curve.data_path for curve in action.fcurves})
        animated_bones = sorted(
            {
                path.split('pose.bones["', 1)[1].split('"]', 1)[0]
                for path in animated_paths
                if path.startswith('pose.bones["') and '"]' in path
            }
        )
        samples_by_bone = {name: [] for name in animated_bones}
        scene.frame_set(first)
        scene.view_layers.update()
        baseline_by_bone = {
            name: armature.matrix_world @ armature.pose.bones[name].matrix.copy()
            for name in animated_bones
        }
        for frame in frames:
            scene.frame_set(int(frame), subframe=float(frame) - int(frame))
            scene.view_layers.update()
            for bone_name in animated_bones:
                require(bone_name in armature.pose.bones, f"missing animated bone {bone_name!r}")
                pose_bone = armature.pose.bones[bone_name]
                pose_world = armature.matrix_world @ pose_bone.matrix
                # glTF import can encode bind-orientation changes in the action
                # itself, so the armature rest matrix is not necessarily the
                # displayed neutral pose.  Measure visible action displacement
                # against this action's first displayed frame instead.
                relative = pose_world @ baseline_by_bone[bone_name].inverted()
                translation, rotation, scale = relative.decompose()
                axis, angle = rotation.to_axis_angle()
                samples_by_bone[bone_name].append(
                    {
                        "frame": frame,
                        "relative_matrix": matrix_rows(relative),
                        "translation_native": finite_vector(translation),
                        "rotation_axis_world": finite_vector(axis),
                        "rotation_angle_rad": float(angle),
                        "scale": finite_vector(scale),
                    }
                )
        bone_reports = []
        for bone_name, samples in samples_by_bone.items():
            translations = [math.sqrt(sum(value * value for value in sample["translation_native"])) for sample in samples]
            rotations = [abs(sample["rotation_angle_rad"]) for sample in samples]
            scales = [max(abs(value - 1.0) for value in sample["scale"]) for sample in samples]
            bone = armature.data.bones[bone_name]
            bone_reports.append(
                {
                    "bone": bone_name,
                    "rest_head_world_native": finite_vector(armature.matrix_world @ bone.head_local),
                    "rest_tail_world_native": finite_vector(armature.matrix_world @ bone.tail_local),
                    "baseline_frame": first,
                    "baseline_pose_matrix": matrix_rows(baseline_by_bone[bone_name]),
                    "maximum_relative_translation_native": max(translations),
                    "maximum_relative_rotation_rad": max(rotations),
                    "maximum_relative_scale_deviation": max(scales),
                    "samples": samples,
                }
            )
        action_reports.append(
            {
                "name": action.name,
                "frame_range": [float(action.frame_range[0]), float(action.frame_range[1])],
                "keyframes": keyframes,
                "animated_data_paths": animated_paths,
                "animated_bones": bone_reports,
            }
        )

    report = {
        "schema_version": 1,
        "source": str(source),
        "source_sha256": actual_hash,
        "source_record": str(SOURCE_RECORD.relative_to(PROJECT_ROOT)),
        "status": "artist_animation_audit_not_physical_calibration",
        "coordinate_unit": "source_native_unit",
        "time_unit": "artist_frame_not_seconds",
        "armature": armature.name,
        "toolchain": {
            "blender_version": actual_blender,
            "blender_version_string": bpy.app.version_string,
            "blender_build_hash": (
                bpy.app.build_hash.decode("utf-8", errors="replace")
                if isinstance(bpy.app.build_hash, bytes)
                else str(bpy.app.build_hash)
            ),
            "python_version": sys.version,
        },
        "scene_unit_settings": {
            "system": scene.unit_settings.system,
            "scale_length": scene.unit_settings.scale_length,
        },
        "actions": action_reports,
        "limitations": [
            "Artist keyframes are appearance evidence only; they are not measured joint limits, timing, force, damping or Xbox revision evidence.",
            "Rest bone heads are candidate visual pivots only and remain unverified against the target controller.",
            "The source-native coordinate scale is not assigned metres by this audit.",
        ],
        "harness_checks": {
            "pinned_source_hash": True,
            "pinned_blender_version": True,
            "single_armature": True,
            "all_actions_have_keyframes": True,
            "all_sampled_transforms_finite": True,
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"ARTIST_ANIMATION_AUDIT_OK actions={len(actions)} output={output}")


if __name__ == "__main__":
    main()
