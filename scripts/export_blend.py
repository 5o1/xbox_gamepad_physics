"""Run with Blender --background --disable-autoexec --python ... -- INPUT OUTPUT.

Exports evaluated object geometry in the unchanged source world coordinate frame.
Does NOT infer meter scale, mechanical pivots, collision shapes or mass properties.
"""

import hashlib
import json
from pathlib import Path
import re
import sys

import bpy

EXPECTED = "53d6eb75352fdf497984a8344b6196283506b88e4424eef601e371c6234bb756"


def main():
    source, output = map(Path, sys.argv[sys.argv.index("--") + 1 :])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if digest != EXPECTED:
        raise ValueError("Unrecognized source: update provenance before export")
    output.mkdir(parents=True, exist_ok=False)
    bpy.ops.wm.open_mainfile(filepath=str(source), use_scripts=False)
    graph = bpy.context.evaluated_depsgraph_get()
    records = []
    for index, obj in enumerate(
        sorted(bpy.context.scene.objects, key=lambda o: o.name)
    ):
        record = dict(
            name=obj.name,
            type=obj.type,
            hidden_render=obj.hide_render,
            source_matrix_world=[list(row) for row in obj.matrix_world],
            mechanical_pivot=None,
            meters_per_native_unit=None,
        )
        if obj.type != "MESH":
            records.append(record)
            continue
        evaluated = obj.evaluated_get(graph)
        mesh = evaluated.to_mesh()
        mesh.calc_loop_triangles()
        vertices = [evaluated.matrix_world @ v.co for v in mesh.vertices]
        triangles = [tuple(t.vertices) for t in mesh.loop_triangles]
        # Reflection changes handedness: correct face winding, not coordinates.
        if evaluated.matrix_world.to_3x3().determinant() < 0:
            triangles = [(a, c, b) for a, b, c in triangles]
        filename = f"{index:02d}_{re.sub(r'[^a-zA-Z0-9_-]', '_', obj.name)}.obj"
        path = output / filename
        with path.open("w") as handle:
            handle.write("# Visual source coordinates; units and dynamics unverified\n")
            for v in vertices:
                handle.write("v " + " ".join(f"{x:.12g}" for x in v) + "\n")
            for tri in triangles:
                handle.write("f " + " ".join(str(i + 1) for i in tri) + "\n")
        bounds = (
            [
                [min(v[i] for v in vertices) for i in range(3)],
                [max(v[i] for v in vertices) for i in range(3)],
            ]
            if vertices
            else None
        )
        materials = []
        for slot in obj.material_slots:
            mat = slot.material
            if mat:
                materials.append(
                    {"name": mat.name, "diffuse_rgba": list(mat.diffuse_color)}
                )
        record.update(
            file=filename,
            sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            vertices=len(vertices),
            triangles=len(triangles),
            bounds_native=bounds,
            modifiers=[m.type for m in obj.modifiers],
            materials=materials,
            material_note="OBJ has no material binding; original material names/colors retained here",
        )
        records.append(record)
        evaluated.to_mesh_clear()
    manifest = dict(
        source_id="xbox_visual",
        source_sha256=digest,
        blender_version=bpy.app.version_string,
        declared_scene_unit_system=bpy.context.scene.unit_settings.system,
        declared_scene_scale=bpy.context.scene.unit_settings.scale_length,
        meters_per_native_unit=None,
        physical_scale_note="Scene metadata does not override upstream non-dimensional warning",
        status="visual_parts_only_not_physical_asset",
        objects=records,
    )
    (output / "inventory.json").write_text(json.dumps(manifest, indent=2))
    print(
        json.dumps(
            {
                "objects": len(records),
                "mesh_objects": sum(r["type"] == "MESH" for r in records),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
