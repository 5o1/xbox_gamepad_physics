"""Single gamepad; in-place root type toggle at physics boundaries."""
from .session import articulation_data, collision_allowed


class GamepadSwitch:
    def __init__(self, scene, pad, cfg):
        self.scene, self.active = scene, pad
        self.frozen = pad.articulation.root.joint.type == 'fixed'
        self.groups = self.group_audit()
        all_groups = [g for shapes in self.groups.values() for g in shapes]
        if any(collision_allowed(a,b) for a in all_groups for b in all_groups):
            raise ValueError('gamepad loader self-collision exclusion is missing')
        if pad.articulation.dof != 20:
            raise ValueError('gamepad freeze requires the full 20-joint articulation')
        self.last_transition = None

    @property
    def role(self):
        return 'fixed' if self.frozen else 'moving'

    def toggle(self):
        from xbox_gamepad_physics.state import XBOX_ONE_S_CHANNELS
        before = self.active.gamepad_state()
        art = self.active.articulation
        data = articulation_data(art, True)
        old_role = self.role
        art.root.joint.type = 'free' if self.frozen else 'fixed'
        self.frozen = not self.frozen
        if not self.frozen:
            art.set_root_linear_velocity([0,0,0])
            art.set_root_angular_velocity([0,0,0])
        art.root.wake_up()
        after = self.active.gamepad_state()
        self.last_transition = {'from':old_role, 'to':self.role, 'pose':data['pose'],
                                'joint_positions':data['joints'], 'drive_targets':data['drive_targets'],
                                'signal_delta':{n:after.channel(n)-before.channel(n) for n in XBOX_ONE_S_CHANNELS}}
        return self.last_transition

    def group_audit(self):
        return {l.name:[list(s.get_collision_groups()) for s in l.get_collision_shapes()]
                for l in self.active.articulation.get_links()}
