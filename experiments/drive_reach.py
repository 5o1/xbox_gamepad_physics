"""K4: drive each joint to both endpoints for one second with a fixed root."""
def internal_contact_pairs(scene, articulation):
    links = set(articulation.get_links())
    return sum(1 for contact in scene.get_contacts() if all(body in links for body in contact.bodies))


def run(cfg, ctx):
    import numpy as np
    from xbox_gamepad_physics import load_motion_contract
    motion = load_motion_contract(cfg["profile"])
    gamepad, scene = ctx.gamepad, ctx.scene
    rows, max_internal = [], 0
    steps = round(1.0 / cfg["scene"]["timestep"])
    for item in motion.joints:
        gamepad.set_joint_positions({name: 0.0 for name in gamepad.joint_names})
        gamepad.articulation.set_qvel(np.zeros(len(gamepad.joint_names)))
        for other in motion.joints:
            gamepad.set_joint_target(other.name, 0.0)
        for side, target in (("upper", item.upper), ("lower", item.lower)):
            gamepad.set_joint_target(item.name, target)
            for _ in range(steps):
                scene.step()
                max_internal = max(max_internal, internal_contact_pairs(scene, gamepad.articulation))
            observed = gamepad.joint_position(item.name)
            fraction = ((observed - item.lower) if side == "upper" else (item.upper - observed)) / (item.upper - item.lower)
            rows.append({"joint": item.name, "side": side, "target": target,
                         "qpos": observed, "unit": item.unit, "reached_fraction": fraction,
                         "passed": fraction >= 0.95})
    return {"collision": cfg["gamepad"]["collision"], "endpoint_seconds": 1.0,
            "results": rows, "max_internal_contact_pairs": max_internal,
            "passed": all(row["passed"] for row in rows) and max_internal == 0}
