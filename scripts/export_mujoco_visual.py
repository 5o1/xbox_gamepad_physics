"""Export the reviewed static parts to a MuJoCo visual-only MJCF asset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
COMMON = (
    ROOT
    / "src"
    / "xbox_gamepad_physics"
    / "resource_data"
    / "common"
    / "xbox_one_s"
    / "visual"
)


def accessor(document: dict[str, Any], binary: bytes, index: int) -> np.ndarray:
    """Read the tightly or interleaved glTF accessor used by the source parts."""

    item = document["accessors"][index]
    view = document["bufferViews"][item["bufferView"]]
    shapes = {"SCALAR": 1, "VEC2": 2, "VEC3": 3}
    component_types = {
        5123: np.dtype("<u2"),
        5125: np.dtype("<u4"),
        5126: np.dtype("<f4"),
    }
    width = shapes[item["type"]]
    dtype = component_types[item["componentType"]]
    return np.ndarray(
        (item["count"], width),
        dtype=dtype,
        buffer=binary,
        offset=view.get("byteOffset", 0) + item.get("byteOffset", 0),
        strides=(view.get("byteStride", dtype.itemsize * width), dtype.itemsize),
    ).copy()


def xml_text(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=False) + "\n"


def add_assets(root: ET.Element, parts: list[dict[str, Any]], scale: float) -> None:
    asset = ET.SubElement(root, "asset")
    ET.SubElement(
        asset,
        "texture",
        name="xbox_base_color",
        type="2d",
        file="textures/base_color.png",
        colorspace="sRGB",
        vflip="true",
    )
    ET.SubElement(
        asset,
        "material",
        name="xbox_surface",
        texture="xbox_base_color",
        rgba="1 1 1 1",
        specular=".5",
        shininess=".2",
        reflectance="0",
    )
    ET.SubElement(
        asset,
        "material",
        name="table_gray",
        rgba=".24 .28 .32 1",
        specular=".15",
        shininess=".1",
        reflectance="0",
    )
    ET.SubElement(
        asset,
        "material",
        name="wall_pink",
        rgba="1 .9 .9 1",
        specular=".1",
        shininess=".05",
        reflectance="0",
    )
    scale_text = f"{scale:.15g} {scale:.15g} {scale:.15g}"
    for part in parts:
        ET.SubElement(
            asset,
            "mesh",
            name=part["name"],
            file="meshes/" + part["file"],
            scale=scale_text,
            smoothnormal="false",
        )


def add_gamepad(
    parent: ET.Element, parts: list[dict[str, Any]], position: str
) -> ET.Element:
    body = ET.SubElement(
        parent,
        "body",
        name="xbox_root",
        pos=position,
        quat=".707106781186548 .707106781186548 0 0",
    )
    for part in parts:
        ET.SubElement(
            body,
            "geom",
            name="visual_" + part["name"],
            type="mesh",
            mesh=part["name"],
            material="xbox_surface",
            contype="0",
            conaffinity="0",
            group="1",
        )
    return body


def add_common(root: ET.Element) -> None:
    ET.SubElement(
        root,
        "compiler",
        angle="radian",
        autolimits="true",
        discardvisual="false",
    )
    ET.SubElement(root, "option", gravity="0 0 -9.81")
    visual = ET.SubElement(root, "visual")
    ET.SubElement(visual, "global", offwidth="1600", offheight="900")
    ET.SubElement(visual, "quality", shadowsize="4096")
    ET.SubElement(
        visual,
        "headlight",
        ambient=".25 .25 .25",
        diffuse=".7 .7 .7",
        specular=".2 .2 .2",
    )
    ET.SubElement(visual, "rgba", haze=".15 .15 .15 1")


def export_meshes(output: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    meshes = output / "meshes"
    meshes.mkdir(parents=True, exist_ok=True)
    binary = (COMMON / "meshes.bin").read_bytes()
    parts: list[dict[str, Any]] = []

    for item in manifest["parts"]:
        document = json.loads(
            (COMMON / item["file"]).read_text(encoding="utf-8")
        )
        primitive = document["meshes"][0]["primitives"][0]
        vertices = accessor(document, binary, primitive["attributes"]["POSITION"])
        normals = accessor(document, binary, primitive["attributes"]["NORMAL"])
        uv = accessor(document, binary, primitive["attributes"]["TEXCOORD_0"])
        faces = (
            accessor(document, binary, primitive["indices"])
            .reshape(-1, 3)
            .astype(np.int64)
            + 1
        )
        if len(vertices) != len(normals) or len(vertices) != len(uv):
            raise ValueError(f"attribute count mismatch in {item['file']}")

        name = item["name"]
        filename = name + ".obj"
        with (meshes / filename).open("w", encoding="utf-8") as stream:
            stream.write(
                "# Visual mesh with source normals and UVs; no collision semantics.\n"
            )
            np.savetxt(stream, vertices, fmt="v %.9g %.9g %.9g")
            np.savetxt(stream, uv, fmt="vt %.9g %.9g")
            np.savetxt(stream, normals, fmt="vn %.9g %.9g %.9g")
            for face in faces:
                stream.write(
                    "f " + " ".join(f"{i}/{i}/{i}" for i in face) + "\n"
                )
        parts.append(
            {
                "name": name,
                "file": filename,
                "vertices": len(vertices),
                "triangles": len(faces),
            }
        )
    return parts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            ROOT
            / "src"
            / "xbox_gamepad_physics"
            / "resource_data"
            / "mujoco"
            / "visual_v0"
        ),
    )
    args = parser.parse_args()
    output = args.output
    textures = output / "textures"
    textures.mkdir(parents=True, exist_ok=True)

    manifest = json.loads((COMMON / "manifest.json").read_text(encoding="utf-8"))
    parts = export_meshes(output, manifest)
    shutil.copyfile(COMMON / "textures" / "base_color.png", textures / "base_color.png")
    scale = manifest["meters_per_native_unit"]

    asset = ET.Element("mujoco", model="xbox_one_s_visual")
    add_common(asset)
    add_assets(asset, parts, scale)
    world = ET.SubElement(asset, "worldbody")
    add_gamepad(world, parts, "0 0 0")
    (output / "xbox_one_s_visual.xml").write_text(
        xml_text(asset), encoding="utf-8"
    )

    scene = ET.Element("mujoco", model="xbox_one_s_table_visual")
    add_common(scene)
    add_assets(scene, parts, scale)
    world = ET.SubElement(scene, "worldbody")
    ET.SubElement(
        world,
        "geom",
        name="ground",
        type="plane",
        size="3 3 .1",
        rgba=".12 .13 .14 1",
        contype="0",
        conaffinity="0",
    )
    ET.SubElement(
        world,
        "geom",
        name="table",
        type="box",
        pos="0 0 .715",
        size=".6 .35 .025",
        material="table_gray",
        contype="0",
        conaffinity="0",
    )
    ET.SubElement(
        world,
        "geom",
        name="wall",
        type="box",
        pos="0 1 1.5",
        size="3 .6 1.5",
        material="wall_pink",
        contype="0",
        conaffinity="0",
    )
    add_gamepad(world, parts, "0 0 .8")
    ET.SubElement(
        world,
        "camera",
        name="head_camera",
        pos="-.032 -.45 1.35",
        xyaxes="1 0 0 0 .8 .6",
        fovy="37",
    )
    ET.SubElement(
        world,
        "camera",
        name="review_oblique",
        pos=".45 -.55 1.15",
        xyaxes=".773 .633 0 -.283 .346 .894",
        fovy="37",
    )
    (output / "table_scene.xml").write_text(xml_text(scene), encoding="utf-8")

    record = {
        "asset_id": "xbox_one_s",
        "stage": "visual",
        "backend": "mujoco",
        "mujoco_version": "3.15.0",
        "physics_ready": False,
        "parts": parts,
        "scale": scale,
        "source_visual_manifest": "common/xbox_one_s/visual/manifest.json",
        "entrypoint": "xbox_one_s_visual.xml",
        "scenes": {"table": "table_scene.xml"},
        "native_renderer_material": {
            "texture": "base_color.png",
            "vflip": True,
            "specular": 0.5,
            "shininess": 0.2,
            "limitations": [
                "MuJoCo native renderer uses the RGB texture and scalar "
                "specular/shininess.",
                "Normal, occlusion, roughness, metallic and emissive maps remain "
                "in common visual resources for PBR renderers; native MuJoCo "
                "does not render PBR texture roles.",
            ],
        },
    }
    (output / "visual_manifest.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"parts": len(parts), "output": str(output)}))


if __name__ == "__main__":
    main()
