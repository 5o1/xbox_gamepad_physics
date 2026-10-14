"""Single gamepad; in-place root type toggle at physics boundaries."""
from .session import collision_allowed


class GamepadSwitch:
    def __init__(self, scene, pad, cfg):
        self.scene, self.active = scene, pad
        self.groups = self.group_audit()
        all_groups = [g for shapes in self.groups.values() for g in shapes]
        if any(collision_allowed(a,b) for a in all_groups for b in all_groups):
            raise ValueError('gamepad loader self-collision exclusion is missing')
        if pad.articulation.dof != 20:
            raise ValueError('gamepad freeze requires the full 20-joint articulation')
        self.last_transition = None

    @property
    def frozen(self):
        return self.active.root_fixed

    @property
    def role(self):
        return 'fixed' if self.frozen else 'moving'

    def toggle(self):
        self.last_transition = self.active.set_root_fixed(not self.frozen)
        return self.last_transition

    def group_audit(self):
        return {l.name:[list(s.get_collision_groups()) for s in l.get_collision_shapes()]
                for l in self.active.articulation.get_links()}
