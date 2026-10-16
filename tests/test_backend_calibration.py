"""Calibration precedence, atomic structure rejection and explicit unknown values."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from xbox_gamepad_physics.backends.common.calibration import CalibrationOverride, export_resolved, load_calibration, resolve_calibration
from xbox_gamepad_physics.backends.common.model import Evidence, Parameter


def item(value, unit="N/m"):
    return Parameter(value, unit, (Evidence("fixture", "test", "Calibration validation fixture", "Explicit fixture definition", category="fixture_definition"),) if value is not None else (), "Removed by this calibration" if value is None else None).as_dict()


class CalibrationTests(unittest.TestCase):
    def test_no_implicit_configuration_search(self):
        with patch.dict(os.environ, {}, clear=True):
            resolved = resolve_calibration()
        self.assertEqual(resolved.configuration_id, "default:full_controls")

    def test_explicit_path_replaces_environment_and_overrides_win(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Path(directory) / "environment.json", Path(directory) / "explicit.json"
            first.write_text(json.dumps({"physical": {"joints": {"a_press": {"stiffness": item(10)}}}}))
            second.write_text(json.dumps({"physical": {"joints": {"a_press": {"stiffness": item(20)}}}}))
            with patch.dict(os.environ, {"XBOX_GAMEPAD_PHYSICS_CALIBRATION": str(first)}):
                override = load_calibration(second)
                resolved = resolve_calibration(override=override, overrides={"physical": {"joints": {"a_press": {"stiffness": item(30)}}}})
            self.assertEqual(resolved.physical["joints.a_press.stiffness"].value, 30)
            self.assertEqual(len(resolved.source_chain["joints.a_press.stiffness"]), 2)
            export_resolved(resolved, Path(directory) / "resolved.json")
            self.assertEqual(json.loads((Path(directory) / "resolved.json").read_text())["physical"]["joints.a_press.stiffness"]["value"], 30)

    def test_null_revokes_value_without_default_fallback(self):
        resolved = resolve_calibration({"joints.a_press.stiffness": Parameter.from_dict(item(10))}, overrides={"physical": {"joints": {"a_press": {"stiffness": item(None)}}}})
        self.assertIsNone(resolved.physical["joints.a_press.stiffness"].value)
        self.assertEqual(len(resolved.source_chain["joints.a_press.stiffness"]), 1)

    def test_travel_rejected_even_with_valid_other_override(self):
        for field in ("travel", "travel_m", "limits", "ranges", "lower", "upper", "joint_limits"):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "not supported.*no overrides were applied"):
                resolve_calibration(overrides={"physical": {"joints": {"a_press": {"stiffness": item(10), field: item(1)}}}})

    def test_invalid_values_and_units_rejected(self):
        for invalid in (item(-1), {"value": 1, "unit": "N/m"}, item(1, "kg"), {**item(1), "value": True}, {**item(1), "value": float("nan")}, item([1, 2])):
            with self.subTest(invalid=invalid), self.assertRaises((ValueError, TypeError)):
                resolve_calibration(overrides={"physical": {"joints": {"a_press": {"stiffness": invalid}}}})

    def test_conflicting_force_and_stiffness_rejected(self):
        with self.assertRaisesRegex(ValueError, "not both"):
            resolve_calibration(overrides={"physical": {"joints": {"a_press": {"stiffness": item(1), "endpoint_force": item(2, "N")}}}})

    def test_profile_and_schema_mismatch(self):
        for override in (CalibrationOverride(schema_version="future"), CalibrationOverride(profile="left_stick", spawn={"root_mode": "free"})):
            with self.assertRaises(ValueError):
                resolve_calibration(override=override)

    def test_configuration_identity_reproducible(self):
        raw = {"physical": {"contact_materials": {"controller": {"static_friction": item(0.2, "1")}}}}
        self.assertEqual(resolve_calibration(overrides=raw).configuration_id, resolve_calibration(overrides=json.loads(json.dumps(raw))).configuration_id)


if __name__ == "__main__":
    unittest.main()
