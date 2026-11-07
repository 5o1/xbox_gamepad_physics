"""Joint policy readback shared by checkout diagnostics; no scoring or mutation."""

def policy(e):
    return {name: {"type": j.type, "dof": j.dof, "limits": j.get_limits().tolist(),
        "drive_mode": j.drive_mode, "target": j.get_drive_target().tolist(),
        "stiffness": float(j.stiffness), "damping": float(j.damping),
        "force_limit": float(j.force_limit), "max_velocity": float(j.get_max_velocity()),
        "friction": float(j.get_friction())} for name, j in e.joints.items()}
