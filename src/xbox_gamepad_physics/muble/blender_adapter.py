"""Drive the approved Blender objects from a MuBlE body-pose trace.

This module imports Blender only when a Blender operation is requested. Scene
composition and rendering remain the caller's responsibility: open the approved
Xbox scene first, then append or link the desired MuBlE environment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from xbox_gamepad_physics.resources import load_json_resource

from .pose_export import MUBLE_BODY_POSE_TRACE_SCHEMA


def visual_records() -> dict[str, dict[str, Any]]:
    """Return packaged Blender-object metadata for all sixteen visual parts."""

    manifest = load_json_resource("common", "xbox_one_s", "visual/manifest.json")
    records: dict[str, dict[str, Any]] = {}
    for part in manifest.get("parts", []):
        name = part.get("name")
        source_object = part.get("source_object")
        matrix = part.get("source_matrix_world")
        if (
            not isinstance(name, str)
            or not isinstance(source_object, str)
            or not isinstance(matrix, list)
            or len(matrix) != 4
            or any(not isinstance(row, list) or len(row) != 4 for row in matrix)
        ):
            raise ValueError("packaged visual manifest lacks Blender source metadata")
        records[name] = part
    if len(records) != 16 or len({item["source_object"] for item in records.values()}) != 16:
        raise ValueError("packaged visual manifest must describe sixteen unique objects")
    return records


def _blender_modules() -> tuple[Any, Any, Any, Any]:
    try:
        import bpy
        from mathutils import Matrix, Quaternion, Vector
    except ModuleNotFoundError as error:
        raise RuntimeError("Blender Python is required for the MuBlE visual adapter") from error
    return bpy, Matrix, Quaternion, Vector


def open_approved_scene(path: str | Path) -> None:
    """Open the existing approved Blender scene without reconstructing it."""

    bpy, _, _, _ = _blender_modules()
    source = Path(path).resolve(strict=True)
    bpy.ops.wm.open_mainfile(filepath=str(source))


def _pose_matrix(record: Mapping[str, Any], Matrix: Any, Quaternion: Any, Vector: Any) -> Any:
    position = record.get("position")
    quaternion = record.get("quaternion_wxyz")
    if not isinstance(position, list) or len(position) != 3:
        raise ValueError("trace body position must contain three values")
    if not isinstance(quaternion, list) or len(quaternion) != 4:
        raise ValueError("trace body quaternion must contain four values")
    matrix = Quaternion(tuple(float(value) for value in quaternion)).to_matrix().to_4x4()
    matrix.translation = Vector(tuple(float(value) for value in position))
    return matrix


@dataclass
class BlenderPoseBridge:
    """Pose bridge for approved objects already present in the current scene."""

    trace: dict[str, Any]
    objects: dict[str, Any]
    offsets: dict[str, Any]
    world_matrix: Any

    @classmethod
    def from_current_scene(
        cls,
        trace: Mapping[str, Any],
        *,
        world_matrix: Any | None = None,
    ) -> "BlenderPoseBridge":
        bpy, Matrix, Quaternion, Vector = _blender_modules()
        if trace.get("schema") != MUBLE_BODY_POSE_TRACE_SCHEMA:
            raise ValueError(f"trace schema must be {MUBLE_BODY_POSE_TRACE_SCHEMA}")
        frames = trace.get("frames")
        part_to_body = trace.get("part_to_body")
        if not isinstance(frames, list) or not frames or not isinstance(part_to_body, dict):
            raise ValueError("trace needs frames and part_to_body")

        records = visual_records()
        if set(part_to_body) != set(records):
            raise ValueError("trace part_to_body does not match the packaged visual manifest")
        objects: dict[str, Any] = {}
        for part, record in records.items():
            obj = bpy.data.objects.get(record["source_object"])
            if obj is None:
                raise ValueError(f"approved Blender scene is missing {record['source_object']!r}")
            preserved = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = preserved
            objects[part] = obj

        manifest = load_json_resource("common", "xbox_one_s", "visual/manifest.json")
        root = world_matrix.copy() if world_matrix is not None else Matrix.Identity(4)
        source_to_sim = Matrix.Rotation(
            float(manifest["blender_source_to_simulation_rotation_x_rad"]), 4, "X"
        )
        source_scale = Matrix.Scale(float(manifest["meters_per_native_unit"]), 4)
        visual_root = root @ source_to_sim @ source_scale
        neutral = frames[0].get("bodies", {})
        offsets: dict[str, Any] = {}
        for part, body_name in part_to_body.items():
            if body_name not in neutral:
                raise ValueError(f"neutral trace is missing body {body_name!r}")
            body_neutral = root @ _pose_matrix(
                neutral[body_name], Matrix, Quaternion, Vector
            )
            source_matrix = Matrix(records[part]["source_matrix_world"])
            offsets[part] = body_neutral.inverted() @ (visual_root @ source_matrix)
        return cls(dict(trace), objects, offsets, root)

    def apply_frame(self, frame_index: int) -> None:
        """Apply one recorded MuJoCo frame to the approved Blender objects."""

        _, Matrix, Quaternion, Vector = _blender_modules()
        frames = self.trace["frames"]
        if isinstance(frame_index, bool) or not isinstance(frame_index, int):
            raise TypeError("frame_index must be an integer")
        if frame_index < 0 or frame_index >= len(frames):
            raise IndexError(f"frame_index {frame_index} is outside the trace")
        bodies = frames[frame_index]["bodies"]
        for part, body_name in self.trace["part_to_body"].items():
            if body_name not in bodies:
                raise ValueError(f"frame {frame_index} is missing body {body_name!r}")
            body_matrix = self.world_matrix @ _pose_matrix(
                bodies[body_name], Matrix, Quaternion, Vector
            )
            self.objects[part].matrix_world = body_matrix @ self.offsets[part]
