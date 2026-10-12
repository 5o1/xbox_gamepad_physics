"""Shared RoboTwin rendering in a separate process, following completed snapshots."""
import argparse
import json
from pathlib import Path
from types import SimpleNamespace
import time

from .stream.ipc import Latest, SNAPSHOT_CAPACITY, FRAME_CAPACITY, packet
from .views import VIEWS, RENDER_CANDIDATES


def run(args):
    import numpy as np
    import cv2
    import sapien
    from xbox_gamepad_physics.resources import load_json_resource
    from xbox_gamepad_physics.robotwin.visual import attach_visual_to_articulation
    from experiments.scene import look_at, create_render_scene
    from .gripper import derive_urdf, parse_builder
    source = Latest(args.run/"snapshot.mmap", SNAPSHOT_CAPACITY)
    output = Latest(args.run/"frame.mmap", FRAME_CAPACITY)
    while not (data := source.read()):
        time.sleep(.01)
    snapshot = json.loads(data[1])
    settings = RENDER_CANDIDATES[args.candidate]
    scene = create_render_scene({"robotwin_root": snapshot["config"]["teleop"]["robotwin_root"],
                                 "timestep": .004}, **settings)
    (args.run/"render_config.json").write_text(json.dumps({"candidate": args.candidate, **settings,
                                                         "path_depth": 8, "views": VIEWS}, indent=2))
    entities = {}
    bodies = {}
    class Skeleton:
        def find_link_by_name(self, name):
            return SimpleNamespace(entity=entities[("gamepad",name)])
    for name in snapshot["gamepad"]["links"]:
        entity = sapien.Entity()
        entity.name = name
        entities[("gamepad",name)] = entity
        scene.add_entity(entity)
    manifest = load_json_resource("robotwin", "full_controls")
    visual = attach_visual_to_articulation(Skeleton(), manifest["visual_binding"])
    bodies.update({("gamepad",name): body for name,body in visual.components.items()})
    path = derive_urdf(snapshot["config"]["teleop"]["robotwin_root"], args.run/"render_derived")
    cfg = dict(snapshot["config"]["teleop"], attach_visual=True)
    builder = parse_builder(scene, path, False, cfg)
    for role in ("main","secondary"):
        for link in builder.link_builders:
            entity = sapien.Entity()
            entity.name = role+"/"+link.name
            body = link.build_render_component()
            entity.add_component(body)
            scene.add_entity(entity)
            entities[(role,link.name)] = entity
            bodies[(role,link.name)] = body
    ball_entity = None
    if "probe" in snapshot:
        builder_ball = scene.create_actor_builder()
        builder_ball.add_sphere_visual(radius=snapshot["probe"]["radius_m"],
            material=sapien.render.RenderMaterial(base_color=[1,.12,.03,1],roughness=.4))
        ball_entity = sapien.Entity()
        ball_entity.add_component(builder_ball.build_render_component())
        scene.add_entity(ball_entity)
    # Table is a visual-only box in this process.
    fixture = cfg["fixture"]
    table = scene.create_actor_builder()
    table.add_box_visual(half_size=fixture["table_half_size_m"],
                         material=sapien.render.RenderMaterial(base_color=[.28,.31,.34,1],roughness=.85))
    table_entity = sapien.Entity()
    table_entity.add_component(table.build_render_component())
    p = fixture["table_pose"]
    table_entity.set_pose(sapien.Pose(p[:3],p[3:]))
    scene.add_entity(table_entity)
    camera = scene.add_camera("teleop",1280,720,np.deg2rad(45),.001,3)
    view = None
    frame = 0
    deadline = time.monotonic()
    with (args.run/"render_timing.jsonl").open("w") as timing:
        while True:
            delay = deadline-time.monotonic()
            if delay > 0:
                time.sleep(delay)
            start = time.monotonic_ns()
            deadline = max(deadline+1/60, start/1e9)
            data = source.read()
            if data:
                snapshot = json.loads(data[1])
            requested = snapshot.get("view","front")
            if requested != view:
                position,target,fovy,up_hint = VIEWS[requested]
                if requested.startswith("reference_"):
                    z = snapshot["gamepad"]["pose"][2]
                    position = [position[0], position[1], position[2]+z]
                    target = [target[0], target[1], target[2]+z]
                camera.entity.set_pose(look_at(position,target,up_hint))
                camera.set_fovy(np.deg2rad(fovy),True)
                view = requested
            for (role,name),entity in entities.items():
                record = snapshot[role]
                p = record["links"][name]
                entity.set_pose(sapien.Pose(p[:3],p[3:]))
                body = bodies.get((role,name))
                if body:
                    body.visibility = 0 if not record["active"] else .35 if role == "secondary" and snapshot["ghost"] else 1
            if ball_entity is not None:
                p = snapshot["probe"]["pose"]
                ball_entity.set_pose(sapien.Pose(p[:3],p[3:]))
            scene.update_render()
            camera.take_picture()
            rendered = time.monotonic_ns()
            color = camera.get_picture("Color")
            copied = time.monotonic_ns()
            rgb = cv2.cvtColor(cv2.convertScaleAbs(color,alpha=255),cv2.COLOR_RGBA2RGB)
            readback = time.monotonic_ns()
            meta = {k:snapshot[k] for k in ("step","state","ghost","ghost_blocked","geometry_blockers",
                                          "main","secondary","frozen","signals","canonical_state","last_input_seq","input_config",
                                          "received_seq","cancelled_seqs","hold_reason","cursor_config")}
            meta.update({k:snapshot[k] for k in ("gamepad_frozen","gamepad_transition","probe") if k in snapshot})
            meta.update({"frame_id":frame,"view":view,"width":1280,"height":720,"capture_ns":readback,
                         "render_ns":rendered-start,"readback_ns":copied-rendered,"conversion_ns":readback-copied})
            output.write(packet(meta,rgb.tobytes()))
            timing.write(json.dumps({"frame_id":frame,"step":snapshot["step"],"render_ns":rendered-start,
                                     "readback_ns":copied-rendered,"conversion_ns":readback-copied,
                                     "dtype":str(color.dtype),"total_ns":time.monotonic_ns()-start})+"\n")
            frame += 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--candidate", choices=RENDER_CANDIDATES, default="raster")
    run(parser.parse_args())
