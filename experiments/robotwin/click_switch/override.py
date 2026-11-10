"""Process-only click limit prototype. No signal/qpos/qvel writes.

Call handle.pre_step() once before each physics step in a real integration.
The context manager inserts that call at scene.step for unchanged diagnostics.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import time
from unittest.mock import patch
import weakref


class ClickSwitch:
    def __init__(self, handle, *, mode, preload, apply_preload, scene, epsilon_m=1e-6, measure=False):
        self.handle = weakref.proxy(handle)
        self.mode = mode
        self.preload = dict(preload)
        self.apply_preload = apply_preload
        self.scene = weakref.proxy(scene)
        self.art = handle.articulation
        self.epsilon_m = epsilon_m
        self.measure = measure
        reference = Path(__file__).resolve().parents[3]/'references/full_controls.json'
        sticks = json.loads(reference.read_text())['control_groups']['sticks']
        self.unlock_n = float(sticks['click_force_n'])
        # Hardware rebound force is unknown. This is only a relock guard;
        # it adds no holding force and never closes a limit until q <= epsilon.
        self.release_n = self.unlock_n
        self.travel_m = float(sticks['click_travel_m'])
        self.joints = []
        self.locked = [True, True]
        self.last_load_n = [0., 0.]
        self.transitions = []
        self.steps = 0
        self.native_ns = []
        self.callback_ns = []
        links = self.art.get_links()
        for side in ('left', 'right'):
            binding = handle._bindings[side+'_stick_click']
            joint = binding.joint
            self.joints.append((joint, binding.qpos_offset, links.index(joint.get_child_link())))
            joint.set_limits([[0., 0.]])

    def pre_step(self):
        """Read last-step average incoming wrench, then change limits on edges."""
        forces = self.art.get_link_incoming_joint_forces()
        positions = self.art.get_qpos()
        for i, (joint, qi, li) in enumerate(self.joints):
            load = max(0., -float(forces[li, 0]))
            self.last_load_n[i] = load
            q = float(positions[qi])
            if self.locked[i] and load >= self.unlock_n:
                joint.set_limits([[0., self.travel_m]])
                if self.mode == 'hybrid':
                    self.apply_preload(self.art, self.scene, {joint.name:self.preload[joint.name]})
                self.locked[i] = False
                self.transitions.append(dict(step=self.steps, joint=joint.name,
                    state='unlocked', q_m=q, axial_load_n=load))
            elif not self.locked[i] and q <= self.epsilon_m and load < self.release_n:
                joint.set_limits([[0., 0.]])
                if self.mode == 'hybrid':
                    self.apply_preload(self.art, self.scene, {joint.name:-self.preload[joint.name]})
                self.locked[i] = True
                self.transitions.append(dict(step=self.steps, joint=joint.name,
                    state='locked', q_m=q, axial_load_n=load))
        self.steps += 1

    def snapshot(self):
        return dict(mode=self.mode, steps=self.steps, epsilon_m=self.epsilon_m, unlock_n=self.unlock_n,
            release_guard_n=self.release_n, locked=self.locked[:],
            last_load_n=self.last_load_n[:], transitions=self.transitions[:],
            qpos=self.art.get_qpos().tolist(), qf=self.art.get_qf().tolist(),
            sleeping=bool(self.art.root.sleeping), sleep_threshold=self.art.get_sleep_threshold(),
            limits={j.name:j.get_limits().tolist() for j, _, _ in self.joints})


@contextmanager
def policy(*, mode, epsilon_m=1e-6, measure=False):
    import xbox_gamepad_physics.robotwin.loader as loader
    from xbox_gamepad_physics.robotwin import mappings
    original_configure = loader._configure_joints
    original_preload = mappings.apply_preload
    handles = weakref.WeakValueDictionary()
    switches = []
    original_steps = []

    def configure(*args, **kwargs):
        handle = original_configure(*args, **kwargs)
        handles[id(handle.articulation)] = handle
        return handle

    def replace_preload(articulation, scene, preload):
        # The station passes _PhysicsScene as a URDF adapter, but its
        # backend steps the underlying scene. Attach to that actual owner.
        scene = getattr(scene, "_scene", scene)
        # Suppress the original preload write, preserving any caller's qf.
        handle = handles[id(articulation)]
        switch = ClickSwitch(handle, mode=mode, preload=preload, apply_preload=original_preload,
                             scene=scene, epsilon_m=epsilon_m, measure=measure)
        handle.click_switch = switch
        handle.pre_step = switch.pre_step
        switches.append(switch)
        native_step = scene.step
        original_steps.append((weakref.ref(scene), native_step))

        def step():
            if measure:
                start = time.perf_counter_ns()
                switch.pre_step()
                before_native = time.perf_counter_ns()
                result = native_step()
                after_native = time.perf_counter_ns()
                switch.callback_ns.append(before_native-start)
                switch.native_ns.append(after_native-before_native)
                return result
            switch.pre_step()
            return native_step()
        scene.step = step

    with patch.object(loader, '_configure_joints', side_effect=configure), \
         patch.object(mappings, 'apply_preload', side_effect=replace_preload):
        try:
            yield switches
        finally:
            for ref, native_step in original_steps:
                scene = ref()
                if scene is not None:
                    scene.step = native_step
