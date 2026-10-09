"""Render full-control MuJoCo review frames with the archived PBR textures.

The review MJCF is derived at runtime from the packaged physical model.  It
changes only render materials, cameras, and the review table; mechanism qpos,
joint names, and signal mappings remain those of the packaged profile.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

from render_robotwin_full_controls_review import GROUPS, sequence


TEXTURES = (
    ("xbox_rgb", "base_color.png", "3", "sRGB", "rgb"),
    ("xbox_normal", "normal.png", "3", "linear", "normal"),
    ("xbox_occlusion", "occlusion.png", "1", "linear", "occlusion"),
    ("xbox_roughness", "roughness.png", "1", "linear", "roughness"),
    ("xbox_metallic", "metallic.png", "1", "linear", "metallic"),
    ("xbox_opacity", "opacity.png", "1", "linear", "opacity"),
    ("xbox_emissive", "emissive_rgba.png", "4", "sRGB", "emissive"),
)


def build_review_xml(
    package_root: Path,
    output: Path,
    *,
    source_filename: str = "xbox_one_s.xml",
) -> Path:
    resource_root = package_root / "xbox_gamepad_physics" / "resource_data" / "mujoco"
    profile_root = resource_root / "full_controls_estimated_v0"
    visual_root = resource_root / "visual_v0"
    source_path = (profile_root / source_filename).resolve(strict=True)
    root = ET.parse(source_path).getroot()

    visual = root.find("visual")
    if visual is None:
        visual = ET.Element("visual")
        root.insert(2, visual)
    ET.SubElement(visual, "global", offwidth="1280", offheight="720")
    ET.SubElement(visual, "quality", shadowsize="4096")
    ET.SubElement(
        visual,
        "headlight",
        ambient=".25 .25 .25",
        diffuse=".7 .7 .7",
        specular=".2 .2 .2",
    )
    ET.SubElement(visual, "rgba", haze=".15 .15 .15 1")

    asset = root.find("asset")
    if asset is None:
        raise ValueError("packaged physical MJCF has no asset section")
    for child in list(asset):
        if child.tag in {"texture", "material"}:
            asset.remove(child)
        elif child.tag == "mesh":
            source = (profile_root / child.get("file")).resolve(strict=True)
            child.set("file", str(source))

    insertion_index = 0
    for name, filename, channels, colorspace, _ in TEXTURES:
        source = (visual_root / "textures" / filename).resolve(strict=True)
        asset.insert(
            insertion_index,
            ET.Element(
                "texture",
                name=name,
                type="2d",
                file=str(source),
                nchannel=channels,
                colorspace=colorspace,
                vflip="true",
            ),
        )
        insertion_index += 1
    surface = ET.Element(
        "material",
        name="xbox_surface",
        rgba="1 1 1 1",
        emission="10",
        specular="1",
        metallic="1",
        roughness="1",
        reflectance="0",
    )
    for name, _, _, _, role in TEXTURES:
        ET.SubElement(surface, "layer", texture=name, role=role)
    asset.insert(insertion_index, surface)
    insertion_index += 1
    asset.insert(
        insertion_index,
        ET.Element(
            "material",
            name="review_table",
            rgba=".24 .28 .32 1",
            specular=".15",
            shininess=".1",
            reflectance="0",
        ),
    )
    asset.insert(
        insertion_index + 1,
        ET.Element(
            "material",
            name="review_wall",
            rgba=".82 .84 .87 1",
            specular=".1",
            shininess=".05",
            reflectance="0",
        ),
    )

    world = root.find("worldbody")
    if world is None:
        raise ValueError("packaged physical MJCF has no worldbody")
    for geom in world.iter("geom"):
        if (geom.get("name") or "").endswith("contact_probe_geom"):
            geom.set("group", "3")
    ET.SubElement(
        world,
        "geom",
        name="review_ground",
        type="plane",
        pos="0 0 -.061",
        size="1 1 .1",
        material="review_table",
        group="2",
        contype="0",
        conaffinity="0",
    )
    ET.SubElement(
        world,
        "geom",
        name="review_table_top",
        type="box",
        pos="0 0 -.086",
        size=".35 .26 .025",
        material="review_table",
        group="2",
        contype="0",
        conaffinity="0",
    )
    ET.SubElement(
        world,
        "geom",
        name="review_wall_back",
        type="box",
        pos="0 .42 .22",
        size=".6 .02 .32",
        material="review_wall",
        group="2",
        contype="0",
        conaffinity="0",
    )
    ET.SubElement(
        world,
        "camera",
        name="review_camera",
        pos="-.00210270656536868 -.0313724614967611 .235769413805947",
        xyaxes="1 0 0 0 .984562508098041 .175033332961735",
        fovy="35",
    )

    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{Path(source_filename).stem}_filament_review.xml"
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=False)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, default=12)
    parser.add_argument("--graphics", default="opengl_headless")
    parser.add_argument("--groups", nargs="+", choices=GROUPS, default=GROUPS)
    args = parser.parse_args()

    package_root = args.package_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(package_root))

    import mujoco
    import mujoco._render_filament as mjrf
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from mujoco.experimental.studio import window
    from mujoco.rendering.filament import renderer as filament_renderer

    from xbox_gamepad_physics.mujoco._manifest import load_runtime_manifest
    from xbox_gamepad_physics.mujoco.handle import bind_handle
    from xbox_gamepad_physics.state import (
        GamepadDeviceId,
        GamepadState,
        XBOX_ONE_S_CHANNELS,
    )

    runtime_xml = build_review_xml(package_root, output / "_runtime")
    model = mujoco.MjModel.from_xml_path(str(runtime_xml))
    data = mujoco.MjData(model)
    # Fixed-camera world transforms are stored in MjData.  They are undefined
    # until the first forward pass; converting the camera before this call
    # produces a valid-looking Filament render whose view is effectively empty.
    mujoco.mj_forward(model, data)
    manifest = load_runtime_manifest("full_controls_estimated_v0")
    handle = bind_handle(
        model,
        data,
        joints=manifest.joints,
        sensors=manifest.sensors,
        signal_controller=manifest.signal_controller,
    )

    api = (
        mjrf.GraphicsApi.GRAPHICS_API_VULKAN
        if args.graphics.startswith("vulkan")
        else mjrf.GraphicsApi.GRAPHICS_API_OPENGL
    )
    resource_window = window.Window("Xbox review resources", 32, 32, args.graphics)
    context = mjrf.Context(mjrf.ContextConfig(graphics_api=api))
    renderer = filament_renderer.Renderer(context)
    objects = mjrf.ModelObjects(context, model)
    scene = renderer.scene("xbox_review")
    scene.configure_from_model(model)
    lights = mjrf.ModelLights(scene, objects)
    renderables = mjrf.ModelRenderables(scene, objects)
    options = mujoco.MjvOption()
    options.geomgroup[:] = 0
    options.geomgroup[1] = 1  # licensed visual mesh
    options.geomgroup[2] = 1  # review table and wall
    options.geomgroup[3] = 1  # optional contact probe
    renderables.set_options(options)
    pixels = np.empty((720, 1280, 3), dtype=np.uint8)
    renderer.target("rgb", pixels)
    renderer.view("main", scene="xbox_review", target="rgb")
    camera = mujoco.MjvCamera()
    camera.type = int(mujoco.mjtCamera.mjCAMERA_FIXED)
    camera.fixedcamid = model.camera("review_camera").id
    renderer.update_camera("main", mujoco.mjv_camera2GLCamera(model, data, camera))
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    title_font = ImageFont.truetype(font_path, 24)
    value_font = ImageFont.truetype(font_path, 18)

    reports = []
    for group in args.groups:
        directory = output / group
        directory.mkdir(parents=True, exist_ok=True)
        observed_frames = []
        for frame_index, (label, command, pair_value) in enumerate(sequence(group)):
            target_state = GamepadState.from_mapping(
                command,
                device_id=GamepadDeviceId.XBOX_ONE_S,
                available_channels=XBOX_ONE_S_CHANNELS,
                task_channels=tuple(command),
            )
            handle.set_gamepad_state(target_state)
            handle.set_physical_events({"pair_bind_connect": pair_value})
            mujoco.mj_forward(model, data)
            observed = handle.gamepad_state(task_channels=tuple(command))
            events = handle.physical_events()
            active = [
                f"{name}={observed.channel(name):+.2f}"
                for name in XBOX_ONE_S_CHANNELS
                if abs(observed.channel(name)) >= 0.05
            ]
            if events.get("pair_bind_connect", 0.0) >= 0.05:
                active.append(f"pair={events['pair_bind_connect']:.2f}")
            observed_frames.append(
                {
                    "layout_id": observed.layout_id,
                    "values": list(observed.values),
                    "available_mask": list(observed.available_mask),
                    "task_mask": list(observed.task_mask),
                    "device_id": observed.device_id,
                    "telemetry": {
                        "frame_index": frame_index,
                        "phase": label,
                        "target": command,
                        "pair_target": pair_value,
                        "pair_observed": events.get("pair_bind_connect", 0.0),
                        "qpos": handle.joint_positions(),
                    },
                }
            )

            lights.update(data)
            renderables.update(data)
            renderer.render()
            image = Image.fromarray(pixels.copy())
            draw = ImageDraw.Draw(image, "RGBA")
            draw.rectangle((18, 17, 935, 112), fill=(24, 27, 31, 235))
            draw.text(
                (34, 29),
                f"MuJoCo qpos readback / Filament PBR | {label}",
                font=title_font,
                fill=(245, 245, 245, 255),
            )
            draw.text(
                (34, 63),
                "  ".join(active)[:105] if active else "neutral",
                font=value_font,
                fill=(80, 220, 255, 255),
            )
            draw.text(
                (34, 89),
                f"frame {frame_index:04d} | prescribed qpos review | video {args.fps} fps",
                font=value_font,
                fill=(205, 210, 215, 255),
            )
            image.save(directory / f"frame_{frame_index:04d}.png")

        trace = {
            "schema_version": 1,
            "review_group": group,
            "backend": "mujoco_filament",
            "profile": "full_controls_estimated_v0",
            "stimulus": "canonical_state_to_mujoco_qpos",
            "signal_source": "mujoco_qpos_readback_after_mj_forward",
            "fps": args.fps,
            "frame_count": len(observed_frames),
            "frames": observed_frames,
        }
        (directory / "observed_trace.json").write_text(
            json.dumps(trace, separators=(",", ":")) + "\n", encoding="utf-8"
        )
        reports.append(
            {
                "group": group,
                "frames": len(observed_frames),
                "trace": f"{group}/observed_trace.json",
                "frame_pattern": f"{group}/frame_%04d.png",
            }
        )

    report = {
        "schema_version": 1,
        "backend": "mujoco_filament",
        "mujoco": mujoco.__version__,
        "profile": "full_controls_estimated_v0",
        "renderer": "filament_pbr_with_opacity_role",
        "graphics": args.graphics,
        "fps": args.fps,
        "groups": reports,
        "signal_source": "mujoco_qpos_readback_after_mj_forward",
        "acceptance": "pending_user_review",
    }
    (output / "render_manifest.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report))
    del resource_window


if __name__ == "__main__":
    main()
