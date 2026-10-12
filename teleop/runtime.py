"""Reproducible scene/fixture setup shared by recording and command replay."""

from pathlib import Path

from .gripper import GripperRig
from .session import Session, pose_data


def fixtures(scene, cfg):
    import numpy as np
    import sapien
    fixture = cfg["fixture"]
    material = scene.create_physical_material(**cfg["material"])
    objects = {}
    for name in ("table", "block"):
        if name == "block" and not fixture.get("include_block", True):
            continue
        builder = scene.create_actor_builder()
        half = fixture[f"{name}_half_size_m"]
        builder.add_box_collision(half_size=half, material=material)
        p = fixture[f"{name}_pose"]
        builder.set_initial_pose(sapien.Pose(p[:3], p[3:]))
        if name == "table":
            entity = builder.build_static(name=name)
            body = entity.find_component_by_type(sapien.physx.PhysxRigidStaticComponent)
        else:
            mass = fixture["block_mass_kg"]
            # Homogeneous cuboid: Ixx=m*(hy^2+hz^2)/3, cyclic permutations.
            inertia = mass/3*np.asarray([half[1]**2+half[2]**2, half[0]**2+half[2]**2, half[0]**2+half[1]**2])
            builder.set_mass_and_inertia(mass, sapien.Pose(), inertia)
            entity = builder.build(name=name)
            body = entity.find_component_by_type(sapien.physx.PhysxRigidDynamicComponent)
        for shape in body.get_collision_shapes():
            shape.set_contact_offset(cfg["contact_offset_m"])
            shape.set_rest_offset(cfg["rest_offset_m"])
        objects[name] = body
    return objects


def make_session(cfg, output, record=None, context=None):
    import sapien
    from experiments.scene import create_scene
    from xbox_gamepad_physics.robotwin import load_into_scene
    from xbox_gamepad_physics.resources import resource_root
    from .site import resolve_config
    cfg = resolve_config(cfg)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if context is None:
        scene = create_scene(cfg["scene"])
        gamepad = load_into_scene(scene, profile=cfg["profile"], **cfg["gamepad"])
    else:
        scene, gamepad = context.scene, context.gamepad
    gamepad_switch = None
    if cfg.get('stream', {}).get('gamepad_freeze', False):
        from .gamepad import GamepadSwitch
        # Use the actual cooked collision geometry of every link, before stepping.
        low = min(float(link.compute_global_aabb_tight()[0][2])
                  for link in gamepad.articulation.get_links() if link.get_collision_shapes())
        p = gamepad.articulation.get_root_pose()
        table_top = cfg['teleop']['fixture']['table_pose'][2] + cfg['teleop']['fixture']['table_half_size_m'][2]
        if not cfg.get('stream',{}).get('preserve_gamepad_pose',False):
            p.p = [p.p[0],p.p[1],p.p[2] + table_top + .0005 - low]
        gamepad.articulation.set_root_pose(p)
        cfg['gamepad']['pose'] = pose_data(p)
        gamepad_switch = GamepadSwitch(scene, gamepad, dict(cfg['gamepad'], profile=cfg['profile']))
    objects = fixtures(scene, cfg["teleop"])
    rig = GripperRig(scene, cfg["teleop"], output/"derived")
    header = {"config": cfg, "sapien": sapien.__version__, "resource_root": str(resource_root()),
              "freeze_mechanism": "fixed_root_driven_articulation",
              "freeze_protocol": "in_place_ratchet_v1",
              "frozen_field": "snapshot alias of main; no frozen replica",
              "group_audit": rig.group_audit(), "fixture_initial": {
                  name: {"pose": pose_data(body.pose)} for name, body in objects.items()}}
    if gamepad_switch:
        header['gamepad_original_groups'] = gamepad_switch.groups
    session = Session(scene, gamepad, rig, cfg["teleop"], record, header)
    session.objects = objects
    session.gamepad_switch = gamepad_switch
    if gamepad_switch:
        for link in gamepad.articulation.get_links():
            session.body_ids[link] = 'gamepad/' + link.name
    return session
