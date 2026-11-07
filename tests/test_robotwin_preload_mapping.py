"""Force-channel composition at the CPU/GPU adapter boundary (no engine)."""
import types
import unittest
import numpy as np
from xbox_gamepad_physics.robotwin.mappings import apply_preload


class PreloadCompositionTest(unittest.TestCase):
    def setUp(self):
        self.joints = [types.SimpleNamespace(name=n, dof=1) for n in ("other", "left_stick_click", "right_stick_click")]

    def test_cpu_load_composes_named_forces(self):
        values = np.array([2., 3., 4.])
        observed = []
        art = types.SimpleNamespace(get_active_joints=lambda: self.joints,
            get_qf=lambda: values, set_qf=lambda q: observed.append(q.copy()))
        apply_preload(art, types.SimpleNamespace(physx_system=object()),
                      {"left_stick_click": -7.4, "right_stick_click": -7.4})
        np.testing.assert_allclose(observed[0], [2., -4.4, -3.4])
        np.testing.assert_array_equal(values, [2., 3., 4.])



if __name__ == "__main__":
    unittest.main()
