"""Physical model semantics and backend mapping boundaries, without any engine."""
import json
import math
from pathlib import Path
import subprocess
import sys
import unittest

import numpy as np

from xbox_gamepad_physics.backends.common.calibration import resolve_calibration
from xbox_gamepad_physics.backends.common.model import Evidence, Parameter, Pose
from xbox_gamepad_physics.backends.common.physical import (MassGeometry, body_mass_properties,
    derive_component_mass, derive_joint_dynamics, derive_physical, evaluate_generalized_force,
    frame_mass_properties, left_stick_links, principal_inertia)

from xbox_gamepad_physics.robotwin.physical import calibrated_contact, configure_robotwin_dynamics, require_robotwin_dynamics

DATA = Path(__file__).resolve().parents[1] / "src/xbox_gamepad_physics/build_data/references"
FULL = json.loads((DATA / "full_controls.json").read_text())
LEFT = json.loads((DATA / "left_stick.json").read_text())


def evidence(value, unit):
    return Parameter(value, unit, (Evidence("fixture", "test", "Test fixture", "Explicit definition", category="fixture_definition"),)).as_dict()


def joints():
    return {"a_press": {"id": "a_press", "limits": [0., .001], "unit": "m"},
            "left_stick_x": {"id": "left_stick_x", "limits": [-.4, .4], "unit": "rad"},
            "left_stick_y": {"id": "left_stick_y", "limits": [-.4, .4], "unit": "rad"}}


class PhysicalTests(unittest.TestCase):
    def test_imports_do_not_import_engines(self):
        script = "import sys; from xbox_gamepad_physics.backends.common import model, calibration, physical; assert not ({'sapien','mujoco','pxr','isaaclab'} & set(sys.modules))"
        subprocess.run([sys.executable, "-c", script], check=True)

    def test_legacy_default_return_and_preload(self):
        actual = derive_joint_dynamics("full_controls", joints(), FULL, LEFT)
        self.assertEqual(actual["a_press"]["stiffness"], 1.57 / .001)
        self.assertEqual(actual["a_press"]["drive_damping"], 2 * .7 * math.sqrt((1.57 / .001) * .001))
        self.assertEqual(actual["a_press"]["passive_damping"], actual["a_press"]["drive_damping"] * .05)
        self.assertEqual(actual["a_press"]["target"], -.015 * .001)
        self.assertNotIn("friction", actual["left_stick_x"])
        configure_robotwin_dynamics(actual, FULL, "full_controls")
        self.assertEqual(actual["left_stick_x"]["friction"], .1)
        self.assertEqual(actual["left_stick_x"]["target"], 0.)

    def test_component_mass_clamp_scales_complete_tensor(self):
        class Properties:
            volume = 1e-10
            mass = 1e-10
            center_mass = np.array([.1, .2, .3])
            inertia = np.array([[4., .1, -.2], [.1, 5., .3], [-.2, .3, 6.]]) * 1e-15
        value = derive_component_mass("a", Properties, FULL)
        self.assertEqual(value["mass_kg"], .0002)
        np.testing.assert_array_equal(value["inertia_kg_m2"], Properties.inertia * (.0002 / 1e-10))
        self.assertEqual(value["com_m"], [.1, .2, .3])

    def test_body_mass_budget_and_frame_policy(self):
        frame = frame_mass_properties()
        body = body_mass_properties(FULL, LEFT, {"moving": .004, "frame": frame["mass_kg"]})
        self.assertEqual(body["mass_kg"], .28 - (.004 + .0005))
        with self.assertRaisesRegex(ValueError, "exceed"):
            body_mass_properties(FULL, LEFT, {"moving": .3})

    def test_principal_inertia_reconstructs_and_is_right_handed(self):
        for tensor in (np.eye(3) * 2e-8, np.diag([1., 2., 2.]), np.array([[4., .3, -.2], [.3, 5., .4], [-.2, .4, 6.]])):
            moments, (w, x, y, z) = principal_inertia(tensor)
            rotation = np.array([[1 - 2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)], [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)], [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
            np.testing.assert_allclose(rotation @ np.diag(moments) @ rotation.T, tensor, atol=1e-14)
            self.assertAlmostEqual(np.linalg.det(rotation), 1.)
            self.assertEqual(sorted(moments), list(moments))
        with self.assertRaises(ValueError):
            principal_inertia(np.diag([-1., 1., 1.]))

    def test_force_clips_drive_before_passive_damper(self):
        records = derive_joint_dynamics("full_controls", joints(), FULL, LEFT)
        description = derive_physical(None, MassGeometry({}, records, FULL, LEFT), resolve_calibration())
        law = description.return_laws["a_press"]
        value = evaluate_generalized_force(law, 1., 2.)
        self.assertEqual(value.drive, -3.14)
        self.assertEqual(value.passive, -law.passive_damping.value * 2.)
        self.assertEqual(value.total, value.drive + value.passive)
        self.assertIsNone(law.dry_friction_effort.value)
        self.assertIsNone(law.armature.value)
        self.assertIsNone(description.contact_materials[0].torsional_resistance_length.value)

    def test_left_slice_preserves_explicit_damping_and_masses(self):
        records = derive_joint_dynamics("left_stick", {name: item for name, item in joints().items() if name != "a_press"}, LEFT)
        self.assertEqual(records["left_stick_x"]["drive_damping"], .00035)
        self.assertEqual(records["left_stick_x"]["passive_damping"], .00035)
        links = left_stick_links(LEFT)
        self.assertEqual(sum(item["mass_kg"] for item in links.values()), .28)

    def test_force_override_uses_frozen_travel_and_backend_mapping_rejects_unknowns(self):
        calibration = resolve_calibration(overrides={"physical": {"joints": {"a_press": {"endpoint_force": evidence(2., "N")}}}})
        actual = derive_joint_dynamics("full_controls", joints(), FULL, LEFT, calibration)
        self.assertEqual(actual["a_press"]["stiffness"], 2000.)
        require_robotwin_dynamics(actual, calibration)
        unknown = resolve_calibration(overrides={"physical": {"joints": {"missing": {"stiffness": evidence(2., "N/m")}}}})
        with self.assertRaisesRegex(ValueError, "unknown joint"):
            derive_joint_dynamics("full_controls", joints(), FULL, LEFT, unknown)
        dry = resolve_calibration(overrides={"physical": {"joints": {"a_press": {"dry_friction_effort": evidence(.1, "N")}}}})
        with self.assertRaisesRegex(ValueError, "no verified mapping"):
            require_robotwin_dynamics(derive_joint_dynamics("full_controls", joints(), FULL, LEFT, dry), dry)

    def test_contact_override_and_null_mapping_failure(self):
        calibration = resolve_calibration(overrides={"physical": {"contact_materials": {"controller": {"static_friction": evidence(.3, "1")}}}})
        self.assertEqual(calibrated_contact(LEFT, calibration)["static_friction"], .3)
        null = resolve_calibration(overrides={"physical": {"contact_materials": {"controller": {"static_friction": {"value": None, "unit": "1", "missing_reason": "Unmeasured"}}}}})
        with self.assertRaisesRegex(ValueError, "not a fallback"):
            calibrated_contact(LEFT, null)

    def test_pose_rejects_non_normalized_and_boolean_values(self):
        for args in (([True, 0, 0], [1, 0, 0, 0]), ([0, 0, 0], [2, 0, 0, 0])):
            with self.assertRaises(ValueError):
                Pose(*args)


if __name__ == "__main__":
    unittest.main()
