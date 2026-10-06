"""Math tests for component envelope, not installed Xbox motion tests."""

import importlib.util
import math
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / "scripts/stick_envelope.py"
spec = importlib.util.spec_from_file_location("envelope", path)
envelope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(envelope)


class StickEnvelopeTests(unittest.TestCase):
    def test_neutral(self):
        self.assertEqual(envelope.lever_direction(0, 0), (0, 0, 1))
        self.assertEqual(envelope.inclination(0, 0), 0)

    def test_cardinal_limit_and_outside(self):
        bound = math.radians(23)
        for sign in (-1, 1):
            self.assertAlmostEqual(envelope.angular_margin(sign * bound, 0, bound), 0)
            self.assertAlmostEqual(envelope.angular_margin(0, sign * bound, bound), 0)
            self.assertLess(envelope.angular_margin(sign * bound * 1.01, 0, bound), 0)

    def test_rectangular_corner_rejected(self):
        bound = math.radians(23)
        for sx in (-1, 1):
            for sy in (-1, 1):
                self.assertLess(
                    envelope.angular_margin(sx * bound, sy * bound, bound), 0
                )

    def test_boundary_and_azimuth_roundtrip(self):
        bound = math.radians(23)
        for degree in range(360):
            angle = math.radians(degree)
            qx, qy = envelope.boundary_coordinates(angle, bound)
            x, y, z = envelope.lever_direction(qx, qy)
            self.assertAlmostEqual(x, math.sin(bound) * math.cos(angle))
            self.assertAlmostEqual(y, math.sin(bound) * math.sin(angle))
            self.assertAlmostEqual(z, math.cos(bound))
            self.assertAlmostEqual(envelope.inclination(qx, qy), bound)

    def test_invalid_input(self):
        for invalid in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                envelope.lever_direction(invalid, 0)
        for invalid in (0, -1, math.pi, math.inf):
            with self.assertRaises(ValueError):
                envelope.angular_margin(0, 0, invalid)


if __name__ == "__main__":
    unittest.main()
