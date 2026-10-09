"""Export the reviewed static parts to a MuJoCo visual-only MJCF asset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
from typing import Any
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image


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
APPROVED_RENDER = ROOT / "assets" / "xbox_one_s" / "approved_render.json"


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


def add_assets(
    root: ET.Element,
    parts: list[dict[str, Any]],
    scale: float,
    *,
    renderer: str,
) -> None:
    asset = ET.SubElement(root, "asset")
    if renderer == "classic":
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
    elif renderer == "filament":
        texture_specs = (
            ("xbox_rgb", "base_color.png", "3", "sRGB", "rgb"),
            ("xbox_normal", "normal.png", "3", "linear", "normal"),
            ("xbox_occlusion", "occlusion.png", "1", "linear", "occlusion"),
            ("xbox_roughness", "roughness.png", "1", "linear", "roughness"),
            ("xbox_metallic", "metallic.png", "1", "linear", "metallic"),
            ("xbox_opacity", "opacity.png", "1", "linear", "opacity"),
            (
                "xbox_emissive",
                "emissive_rgba.png",
                "4",
                "sRGB",
                "emissive",
            ),
        )
        for name, filename, channels, colorspace, _ in texture_specs:
            ET.SubElement(
                asset,
                "texture",
                name=name,
                type="2d",
                file="textures/" + filename,
                nchannel=channels,
                colorspace=colorspace,
                vflip="true",
            )
        material = ET.SubElement(
            asset,
            "material",
            name="xbox_surface",
            rgba="1 1 1 1",
            emission="10",
            specular="1",
            metallic="1",
            roughness="1",
            reflectance="0",
        )
        for name, _, _, _, role in texture_specs:
            ET.SubElement(material, "layer", texture=name, role=role)
    else:
        raise ValueError(f"unknown renderer {renderer!r}")
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


def add_reference_camera(world: ET.Element, scale: float) -> dict[str, Any]:
    """Add the user-approved 35-degree camera after the visual scale transform."""

    approved = json.loads(APPROVED_RENDER.read_text(encoding="utf-8"))
    source_position = np.asarray(approved["camera"]["position"], dtype=float)
    source_target = np.asarray(approved["camera"]["target"], dtype=float)
    position = source_position * scale
    target = source_target * scale
    forward = target - position
    forward /= np.linalg.norm(forward)
    world_up = np.asarray([0.0, 0.0, 1.0])
    right = np.cross(forward, world_up)
    right /= np.linalg.norm(right)
    image_up = np.cross(right, forward)

    def vector_text(values: np.ndarray) -> str:
        return " ".join(f"{value:.15g}" for value in values)

    ET.SubElement(
        world,
        "camera",
        name="reference_camera",
        pos=vector_text(position),
        xyaxes=vector_text(np.concatenate((right, image_up))),
        fovy=str(approved["camera"]["fov_degrees"]),
    )
    return {
        "source_position": source_position.tolist(),
        "source_target": source_target.tolist(),
        "position_m": position.tolist(),
        "target_m": target.tolist(),
        "fovy_degrees": approved["camera"]["fov_degrees"],
        "source": "assets/xbox_one_s/approved_render.json",
        "transform": "Blender Z-up camera coordinates multiplied by visual scale",
    }


def add_table_scene(world: ET.Element, parts: list[dict[str, Any]]) -> None:
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
    for filename in (
        "base_color.png",
        "normal.png",
        "occlusion.png",
        "roughness.png",
        "metallic.png",
    ):
        shutil.copyfile(COMMON / "textures" / filename, textures / filename)

    base_color = Image.open(COMMON / "textures" / "base_color.png").convert("RGBA")
    base_color.getchannel("A").save(textures / "opacity.png")
    emissive = Image.open(COMMON / "textures" / "emissive.png").convert("L")
    Image.merge(
        "RGBA",
        (emissive, emissive, emissive, Image.new("L", emissive.size, 255)),
    ).save(textures / "emissive_rgba.png")
    scale = manifest["meters_per_native_unit"]

    entrypoints = {}
    for renderer in ("classic", "filament"):
        asset = ET.Element("mujoco", model=f"xbox_one_s_{renderer}_visual")
        add_common(asset)
        add_assets(asset, parts, scale, renderer=renderer)
        world = ET.SubElement(asset, "worldbody")
        add_gamepad(world, parts, "0 0 0")
        filename = (
            "xbox_one_s_visual.xml"
            if renderer == "classic"
            else "xbox_one_s_filament.xml"
        )
        (output / filename).write_text(xml_text(asset), encoding="utf-8")
        entrypoints[renderer] = filename

    scenes: dict[str, dict[str, str]] = {"classic": {}, "filament": {}}
    for renderer in ("classic", "filament"):
        scene = ET.Element("mujoco", model=f"xbox_one_s_{renderer}_table_visual")
        add_common(scene)
        add_assets(scene, parts, scale, renderer=renderer)
        add_table_scene(ET.SubElement(scene, "worldbody"), parts)
        filename = (
            "table_scene.xml"
            if renderer == "classic"
            else "table_scene_filament.xml"
        )
        (output / filename).write_text(xml_text(scene), encoding="utf-8")
        scenes[renderer]["table"] = filename

    reference = ET.Element("mujoco", model="xbox_one_s_filament_reference")
    add_common(reference)
    add_assets(reference, parts, scale, renderer="filament")
    reference_world = ET.SubElement(reference, "worldbody")
    add_gamepad(reference_world, parts, "0 0 0")
    reference_camera = add_reference_camera(reference_world, scale)
    reference_filename = "reference_scene_filament.xml"
    (output / reference_filename).write_text(xml_text(reference), encoding="utf-8")
    scenes["filament"]["reference"] = reference_filename

    record = {
        "asset_id": "xbox_one_s",
        "stage": "visual",
        "backend": "mujoco",
        "mujoco_version": "3.15.0",
        "physics_ready": False,
        "parts": parts,
        "scale": scale,
        "source_visual_manifest": "common/xbox_one_s/visual/manifest.json",
        "entrypoint": entrypoints["classic"],
        "scenes": scenes["classic"],
        "renderers": {
            "classic": {
                "entrypoint": entrypoints["classic"],
                "scenes": scenes["classic"],
            },
            "filament": {
                "entrypoint": entrypoints["filament"],
                "scenes": scenes["filament"],
            },
        },
        "reference_camera": reference_camera,
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
        "filament_material": {
            "renderer_requirement": {
                "repository": "https://github.com/5o1/mujoco.git",
                "branch": "concon/filament-opacity-texture",
                "opacity_fix_commit": "fbeb31381564ae71e9efcdf3189d1ffbf5033269",
                "reason": (
                    "MuJoCo 3.15.0 ModelRenderables omits mjTEXROLE_OPACITY "
                    "when translating mjModel materials to Filament."
                ),
            },
            "source_roles": [
                "rgb",
                "opacity",
                "normal",
                "occlusion",
                "roughness",
                "metallic",
                "emissive",
            ],
            "source_factors": {
                "metallic": 1.0,
                "roughness": 1.0,
                "emissive_strength": 10.0,
                "specular_factor": 1.0,
            },
            "derived_textures": {
                "opacity.png": "alpha channel copied from source base_color.png",
                "emissive_rgba.png": (
                    "source grayscale emissive replicated to RGB; alpha exposure "
                    "weight set to 1"
                ),
            },
            "limitations": [
                "MuJoCo 3.15 has no texture role for KHR_materials_specular; "
                "the source scalar specularFactor=1 is retained, while spatial "
                "variation from the specular texture remains unsupported."
            ],
        },
    }
    (output / "visual_manifest.json").write_text(
        json.dumps(record, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"parts": len(parts), "output": str(output)}))


if __name__ == "__main__":
    main()
